"""Decorative per-torrent, Game Boy Tetris-styled download-progress board.

This is a lightweight *real* Tetris physics simulation (2D occupancy grid,
the seven standard tetrominoes, straight-down gravity, per-column skylines)
rather than a scripted fill order. That is deliberate: a rigid left-to-right
fill reads as "just dots appearing, always the same shape", while dropping
actual tetromino shapes onto a real grid naturally produces the varied
shapes, occasional holes, and uneven skyline of a genuinely played Tetris
board, matching a real Game Boy Tetris screenshot far better.

Progress bookkeeping still works exactly like before, though:

* `set_progress(fraction)` only ever updates a *target* cell count. It never
  mutates the grid and never animates synchronously.
* A separate `step()`, driven every animation tick by
  `TetrisProgressWidget`'s QTimer, is the only thing that ever advances the
  simulation (spawns/falls/locks pieces).
* `filled_count` (settled/locked cells) never exceeds `target_filled_count`.
* Because real gravity can trap holes under overhangs that no falling piece
  can ever reach from below, the model switches to a guaranteed "finishing"
  pass for the last small tail of the board (or whenever no standard
  tetromino can be placed anywhere any more): remaining empty cells --
  including previously trapped holes -- are filled directly, with no shape
  constraint, so reaching 100% always means a literally solid board with
  zero holes, even though holes are expected and fine before that.

TetrisBoardModel has zero Qt dependency and is covered by
tests/test_tetris_board_model.py. TetrisProgressWidget is the thin Qt
painting/animation layer on top of it.
"""

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QSize, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

BOARD_ROWS = 8
BOARD_COLS = 18
CELLS_PER_PIECE = 4

# A single falling piece never visibly travels more than this many rows
# before locking, even if its true resting row (computed by gravity) is much
# further down. Without this cap, a tall board could make one piece's fall
# take a very long time to visually catch up -- the same problem the old
# column-major implementation avoided with MAX_TRAVEL_SPAN. We reproduce it
# here by simply starting the piece's on-screen animation partway down
# (close to where it will land) instead of always at the very top.
MAX_FALL_ROWS = 6

# Once the gap between real progress and the animated board exceeds this many
# cells, extra pieces beyond that buffer are locked instantly (no falling
# animation) so the board catches up quickly; the remaining buffer still
# falls piece-by-piece for a normal chunky animation. This is unchanged in
# spirit from the old column-major implementation.
CATCHUP_BUFFER_CELLS = 16

# How many random (shape, rotation, column) combinations to try before
# falling back to an exhaustive search for a valid placement. Keeps the
# common case cheap while still guaranteeing a placement is found if one
# exists anywhere on the board.
SPAWN_ATTEMPTS = 12

# Once the *whole board* has this few empty cells left (regardless of how
# small the current target increment is), stop trying to drop standard
# tetrominoes and instead guarantee completion by filling whatever empty
# cells remain directly. Odd-shaped leftover holes near a fully packed board
# frequently cannot be reached by any of the seven standard shapes, so this
# is what guarantees is_full() is reachable at all, and specifically that it
# is reached with zero remaining holes exactly at 100% progress.
FINISH_TAIL_CELLS = 12

Cells = Tuple[Tuple[int, int], ...]

# The seven standard tetrominoes, expressed as (row, col) offsets from their
# own bounding-box origin, one tuple per rotation state. This does not need
# full SRS wall-kick correctness -- it is a decorative cosmetic drop, not a
# playable game -- just enough rotation variety to look genuinely varied.
TETROMINOES: Dict[str, Tuple[Cells, ...]] = {
    "I": (
        ((0, 0), (0, 1), (0, 2), (0, 3)),
        ((0, 0), (1, 0), (2, 0), (3, 0)),
    ),
    "O": (((0, 0), (0, 1), (1, 0), (1, 1)),),
    "T": (
        ((0, 1), (1, 0), (1, 1), (1, 2)),
        ((0, 0), (1, 0), (1, 1), (2, 0)),
        ((0, 0), (0, 1), (0, 2), (1, 1)),
        ((0, 1), (1, 0), (1, 1), (2, 1)),
    ),
    "S": (
        ((0, 1), (0, 2), (1, 0), (1, 1)),
        ((0, 0), (1, 0), (1, 1), (2, 1)),
    ),
    "Z": (
        ((0, 0), (0, 1), (1, 1), (1, 2)),
        ((0, 1), (1, 0), (1, 1), (2, 0)),
    ),
    "J": (
        ((0, 0), (1, 0), (1, 1), (1, 2)),
        ((0, 0), (0, 1), (1, 0), (2, 0)),
        ((0, 0), (0, 1), (0, 2), (1, 2)),
        ((0, 1), (1, 1), (2, 0), (2, 1)),
    ),
    "L": (
        ((0, 2), (1, 0), (1, 1), (1, 2)),
        ((0, 0), (1, 0), (2, 0), (2, 1)),
        ((0, 0), (0, 1), (0, 2), (1, 0)),
        ((0, 0), (0, 1), (1, 1), (2, 1)),
    ),
}
TETROMINO_NAMES: Tuple[str, ...] = tuple(TETROMINOES.keys())


@dataclass
class FallingPiece:
    shape_name: str
    cells: Cells  # (row, col) offsets from (row, col) origin below
    col: int  # fixed board column of the piece's bounding-box origin
    row: int  # current on-screen row of the piece's bounding-box origin
    target_row: int  # row at which it collides/settles and gets locked

    def cells_on_board(self) -> List[Tuple[int, int]]:
        return [(self.row + dr, self.col + dc) for dr, dc in self.cells]


class TetrisBoardModel:
    """Pure Python model: a `rows` x `cols` occupancy grid. Pieces spawn at
    the top and fall straight down under simple gravity, exactly like real
    Tetris, so the board naturally develops a varied, holey, uneven skyline
    as it fills."""

    def __init__(self, rows: int = BOARD_ROWS, cols: int = BOARD_COLS) -> None:
        self.rows = rows
        self.cols = cols
        self.grid: List[List[bool]] = [[False] * cols for _ in range(rows)]
        self.filled_count = 0
        self.target_filled_count = 0
        self.current_piece: Optional[FallingPiece] = None
        # See FINISH_TAIL_CELLS -- scaled down for small boards so tiny test
        # boards don't spend their *entire* life in finishing mode.
        self._finish_tail = min(FINISH_TAIL_CELLS, max(CELLS_PER_PIECE, self.total_cells // 3))

    @property
    def total_cells(self) -> int:
        return self.rows * self.cols

    def set_progress(self, fraction: float) -> None:
        fraction = max(0.0, min(1.0, fraction))
        self.target_filled_count = round(fraction * self.total_cells)

    def is_full(self) -> bool:
        return self.filled_count >= self.total_cells

    # -- collision / placement helpers ------------------------------------

    def _fits(self, cells: Cells, row: int, col: int) -> bool:
        for dr, dc in cells:
            r, c = row + dr, col + dc
            if r < 0 or r >= self.rows or c < 0 or c >= self.cols:
                return False
            if self.grid[r][c]:
                return False
        return True

    def _drop_row(self, cells: Cells, col: int) -> Optional[int]:
        """Simulate gravity: return the resting row for `cells` spawned at
        `col`, or None if it cannot even be placed at the top (topped out)."""
        if not self._fits(cells, 0, col):
            return None
        row = 0
        while self._fits(cells, row + 1, col):
            row += 1
        return row

    def _find_placement(self) -> Optional[Tuple[str, Cells, int, int]]:
        """Return (shape_name, cells, col, resting_row) for a valid random
        placement, or None if no standard tetromino fits anywhere (topped
        out)."""
        for _ in range(SPAWN_ATTEMPTS):
            shape_name = random.choice(TETROMINO_NAMES)
            cells = random.choice(TETROMINOES[shape_name])
            width = max(dc for _, dc in cells) + 1
            if width > self.cols:
                continue
            col = random.randint(0, self.cols - width)
            resting_row = self._drop_row(cells, col)
            if resting_row is not None:
                return shape_name, cells, col, resting_row

        # Exhaustive fallback: guarantees we find a placement if one exists
        # anywhere, so random bad luck never causes a spurious top-out.
        shapes = list(TETROMINO_NAMES)
        random.shuffle(shapes)
        for shape_name in shapes:
            rotations = list(TETROMINOES[shape_name])
            random.shuffle(rotations)
            for cells in rotations:
                width = max(dc for _, dc in cells) + 1
                if width > self.cols:
                    continue
                columns = list(range(self.cols - width + 1))
                random.shuffle(columns)
                for col in columns:
                    resting_row = self._drop_row(cells, col)
                    if resting_row is not None:
                        return shape_name, cells, col, resting_row
        return None

    # -- locking helpers ----------------------------------------------------

    def _lock_cells(self, cells: List[Tuple[int, int]]) -> int:
        """Mark up to `target_filled_count - filled_count` of `cells`
        occupied. Never locks more than the remaining target allows, which is
        what guarantees filled_count never exceeds target_filled_count."""
        remaining = self.target_filled_count - self.filled_count
        locked = 0
        for r, c in cells:
            if locked >= remaining:
                break
            if not self.grid[r][c]:
                self.grid[r][c] = True
                self.filled_count += 1
                locked += 1
        return locked

    def _lock_piece(self, piece: FallingPiece) -> None:
        self._lock_cells(piece.cells_on_board())

    def _collect_empty_cells(self, limit: int) -> List[Tuple[int, int]]:
        cells: List[Tuple[int, int]] = []
        for r in range(self.rows):
            for c in range(self.cols):
                if not self.grid[r][c]:
                    cells.append((r, c))
                    if len(cells) >= limit:
                        return cells
        return cells

    def _in_finishing_mode(self) -> bool:
        return (self.total_cells - self.filled_count) <= self._finish_tail

    # -- animation ------------------------------------------------------

    def _advance(self, instant: bool) -> bool:
        """Make one piece worth of progress. If `instant`, lock it straight
        away (used for catch-up); otherwise start it falling as
        `current_piece`. Returns True if anything changed."""
        remaining = self.target_filled_count - self.filled_count
        if remaining <= 0:
            return False

        if self._in_finishing_mode():
            # Guaranteed-completion cleanup pass: fill whatever empty cells
            # remain directly, no shape/gravity constraint needed since this
            # is just guaranteeing exact completion, not gameplay realism.
            cells = self._collect_empty_cells(CELLS_PER_PIECE)
            if not cells:
                return False
            self._lock_cells(cells)
            return True

        placement = self._find_placement()
        if placement is None:
            # Topped out: overhangs/holes mean no standard tetromino fits
            # anywhere without an immediate collision. Fall back to filling
            # remaining empty cells directly so progress never gets stuck.
            cells = self._collect_empty_cells(CELLS_PER_PIECE)
            if not cells:
                return False
            self._lock_cells(cells)
            return True

        shape_name, cells, col, resting_row = placement
        if instant:
            board_cells = [(resting_row + dr, col + dc) for dr, dc in cells]
            self._lock_cells(board_cells)
        else:
            start_row = max(0, resting_row - MAX_FALL_ROWS)
            self.current_piece = FallingPiece(
                shape_name=shape_name,
                cells=cells,
                col=col,
                row=start_row,
                target_row=resting_row,
            )
        return True

    def step(self) -> bool:
        """Advance the animation by one tick. Returns True if a repaint is
        warranted (something moved or a piece locked)."""
        if self.current_piece is None:
            changed = False
            # Lock pieces beyond the animated buffer instantly, so a big
            # jump in real progress (resume from disk, a torrent that
            # finishes in a couple of seconds) doesn't take forever to
            # visually catch up. The last CATCHUP_BUFFER_CELLS still animate
            # normally, piece by piece.
            while self.target_filled_count - self.filled_count > CATCHUP_BUFFER_CELLS:
                if not self._advance(instant=True):
                    break
                changed = True

            if self.filled_count < self.target_filled_count:
                if self._advance(instant=False):
                    changed = True
            return changed

        piece = self.current_piece
        if piece.row < piece.target_row:
            piece.row += 1
            return True

        # Reached its resting row: lock it into the settled stack.
        self._lock_piece(piece)
        self.current_piece = None
        return True


# Classic DMG (original Game Boy) 4-shade LCD palette.
_COLOR_EMPTY = QColor(0x9B, 0xBC, 0x0F)  # lightest -- unlit cell
_COLOR_ACTIVE = QColor(0x8B, 0xAC, 0x0F)  # light -- falling piece
_COLOR_SETTLED = QColor(0x30, 0x62, 0x30)  # dark -- settled/locked cell
_COLOR_BORDER = QColor(0x0F, 0x38, 0x0F)  # darkest -- bezel / grid lines

ANIMATION_INTERVAL_MS = 150  # deliberately slow/chunky, well below 60fps
DEFAULT_CELL_PX = 8


class TetrisProgressWidget(QWidget):
    """Per-torrent horizontal Tetris progress indicator. `set_progress()`
    only updates the target; a QTimer drives the actual falling/settling
    animation independently, so animation ticks are decoupled from progress
    updates (one piece does not correspond to a fixed percentage). A small
    numeric readout of the real (non-animated) progress percentage is drawn
    in the corner."""

    def __init__(self, rows: int = BOARD_ROWS, cols: int = BOARD_COLS, parent=None) -> None:
        super().__init__(parent)
        self.model = TetrisBoardModel(rows=rows, cols=cols)
        self._progress_fraction = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(ANIMATION_INTERVAL_MS)

    def set_progress(self, fraction: float) -> None:
        self._progress_fraction = max(0.0, min(1.0, fraction))
        self.model.set_progress(fraction)

    def _on_tick(self) -> None:
        if self.model.step():
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(self.model.cols * DEFAULT_CELL_PX, self.model.rows * DEFAULT_CELL_PX)

    def minimumSizeHint(self) -> QSize:
        return QSize(self.model.cols * 3, self.model.rows * 3)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        rows, cols = self.model.rows, self.model.cols
        cell_w = self.width() / cols
        cell_h = self.height() / rows

        painter.fillRect(self.rect(), _COLOR_BORDER)

        grid = self.model.grid
        for row in range(rows):
            y = round(row * cell_h)
            h = round((row + 1) * cell_h) - y
            for col in range(cols):
                x = round(col * cell_w)
                w = round((col + 1) * cell_w) - x
                color = _COLOR_SETTLED if grid[row][col] else _COLOR_EMPTY
                painter.fillRect(x + 1, y + 1, max(w - 1, 1), max(h - 1, 1), color)

        piece = self.model.current_piece
        if piece is not None:
            for row, col in piece.cells_on_board():
                if row < 0 or row >= rows or col < 0 or col >= cols:
                    continue
                x = round(col * cell_w)
                w = round((col + 1) * cell_w) - x
                y = round(row * cell_h)
                h = round((row + 1) * cell_h) - y
                painter.fillRect(x + 1, y + 1, max(w - 1, 1), max(h - 1, 1), _COLOR_ACTIVE)

        self._paint_percentage(painter)
        painter.end()

    def _paint_percentage(self, painter: QPainter) -> None:
        """Draw the real (immediately-accurate) download percentage in the
        bottom-right corner, on a small dark backing rectangle so it stays
        legible against both light and dark board cells. This is the actual
        progress passed to set_progress(), not the animated fill ratio
        (which lags/decouples from it on purpose)."""
        text = f"{round(self._progress_fraction * 100)}%"

        font = painter.font()
        font.setPixelSize(max(7, min(11, int(self.height() * 0.55))))
        font.setBold(True)
        painter.setFont(font)

        metrics = painter.fontMetrics()
        text_w = metrics.horizontalAdvance(text)
        text_h = metrics.height()
        pad_x, pad_y = 3, 1
        rect_w = text_w + pad_x * 2
        rect_h = text_h + pad_y * 2
        x = max(0, self.width() - rect_w)
        y = max(0, self.height() - rect_h)

        backing = QColor(_COLOR_BORDER)
        backing.setAlpha(190)
        painter.fillRect(x, y, rect_w, rect_h, backing)

        painter.setPen(_COLOR_EMPTY)
        painter.drawText(x + pad_x, y + rect_h - pad_y - metrics.descent(), text)
