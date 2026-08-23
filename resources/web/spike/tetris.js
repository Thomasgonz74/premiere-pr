// Port of TetrisBoardModel (src/torrent2000/ui/widgets/tetris_progress.py) --
// same rules, same constants. Kept close to the Python source on purpose so
// the two stay easy to compare/audit side by side.

const BOARD_ROWS = 8;
const BOARD_COLS = 18;
const CELLS_PER_PIECE = 4;
const MAX_FALL_ROWS = 6;
const CATCHUP_BUFFER_CELLS = 16;
const SPAWN_ATTEMPTS = 12;
const FINISH_TAIL_CELLS = 12;
const ANIMATION_INTERVAL_MS = 150;
const DEFAULT_CELL_PX = 6;

const TETROMINOES = {
  I: [[[0,0],[0,1],[0,2],[0,3]], [[0,0],[1,0],[2,0],[3,0]]],
  O: [[[0,0],[0,1],[1,0],[1,1]]],
  T: [[[0,1],[1,0],[1,1],[1,2]], [[0,0],[1,0],[1,1],[2,0]], [[0,0],[0,1],[0,2],[1,1]], [[0,1],[1,0],[1,1],[2,1]]],
  S: [[[0,1],[0,2],[1,0],[1,1]], [[0,0],[1,0],[1,1],[2,1]]],
  Z: [[[0,0],[0,1],[1,1],[1,2]], [[0,1],[1,0],[1,1],[2,0]]],
  J: [[[0,0],[1,0],[1,1],[1,2]], [[0,0],[0,1],[1,0],[2,0]], [[0,0],[0,1],[0,2],[1,2]], [[0,1],[1,1],[2,0],[2,1]]],
  L: [[[0,2],[1,0],[1,1],[1,2]], [[0,0],[1,0],[2,0],[2,1]], [[0,0],[0,1],[0,2],[1,0]], [[0,0],[0,1],[1,1],[2,1]]],
};
const TETROMINO_NAMES = Object.keys(TETROMINOES);

function choice(arr) { return arr[Math.floor(Math.random() * arr.length)]; }
function randint(lo, hi) { return lo + Math.floor(Math.random() * (hi - lo + 1)); }
function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

class TetrisBoardModel {
  constructor(rows = BOARD_ROWS, cols = BOARD_COLS) {
    this.rows = rows;
    this.cols = cols;
    this.grid = Array.from({ length: rows }, () => new Array(cols).fill(false));
    this.filledCount = 0;
    this.targetFilledCount = 0;
    this.currentPiece = null;
    this.totalCells = rows * cols;
    this._finishTail = Math.min(FINISH_TAIL_CELLS, Math.max(CELLS_PER_PIECE, Math.floor(this.totalCells / 3)));
  }

  setProgress(fraction) {
    fraction = Math.max(0, Math.min(1, fraction));
    this.targetFilledCount = Math.round(fraction * this.totalCells);
  }

  _fits(cells, row, col) {
    for (const [dr, dc] of cells) {
      const r = row + dr, c = col + dc;
      if (r < 0 || r >= this.rows || c < 0 || c >= this.cols) return false;
      if (this.grid[r][c]) return false;
    }
    return true;
  }

  _findPlacement() {
    for (let i = 0; i < SPAWN_ATTEMPTS; i++) {
      const shapeName = choice(TETROMINO_NAMES);
      const cells = choice(TETROMINOES[shapeName]);
      const width = Math.max(...cells.map(([, dc]) => dc)) + 1;
      const height = Math.max(...cells.map(([dr]) => dr)) + 1;
      if (width > this.cols || height > this.rows) continue;
      const row = randint(0, this.rows - height);
      const col = randint(0, this.cols - width);
      if (this._fits(cells, row, col)) return { shapeName, cells, col, row };
    }
    const shapes = shuffle(TETROMINO_NAMES.slice());
    for (const shapeName of shapes) {
      const rotations = shuffle(TETROMINOES[shapeName].slice());
      for (const cells of rotations) {
        const width = Math.max(...cells.map(([, dc]) => dc)) + 1;
        const height = Math.max(...cells.map(([dr]) => dr)) + 1;
        if (width > this.cols || height > this.rows) continue;
        const rows_ = shuffle(Array.from({ length: this.rows - height + 1 }, (_, i) => i));
        const cols_ = shuffle(Array.from({ length: this.cols - width + 1 }, (_, i) => i));
        for (const row of rows_) {
          for (const col of cols_) {
            if (this._fits(cells, row, col)) return { shapeName, cells, col, row };
          }
        }
      }
    }
    return null;
  }

  _lockCells(cells) {
    const remaining = this.targetFilledCount - this.filledCount;
    let locked = 0;
    for (const [r, c] of cells) {
      if (locked >= remaining) break;
      if (!this.grid[r][c]) {
        this.grid[r][c] = true;
        this.filledCount += 1;
        locked += 1;
      }
    }
    return locked;
  }

  _lockPiece(piece) {
    this._lockCells(piece.cells.map(([dr, dc]) => [piece.row + dr, piece.col + dc]));
  }

  _collectEmptyCells(limit) {
    const empty = [];
    for (let r = 0; r < this.rows; r++) for (let c = 0; c < this.cols; c++) if (!this.grid[r][c]) empty.push([r, c]);
    shuffle(empty);
    return empty.slice(0, limit);
  }

  _inFinishingMode() {
    return this.totalCells - this.filledCount <= this._finishTail;
  }

  _advance(instant) {
    const remaining = this.targetFilledCount - this.filledCount;
    if (remaining <= 0) return false;

    if (this._inFinishingMode()) {
      const cells = this._collectEmptyCells(CELLS_PER_PIECE);
      if (!cells.length) return false;
      this._lockCells(cells);
      return true;
    }

    const placement = this._findPlacement();
    if (placement === null) {
      const cells = this._collectEmptyCells(CELLS_PER_PIECE);
      if (!cells.length) return false;
      this._lockCells(cells);
      return true;
    }

    const { shapeName, cells, col, row: targetRow } = placement;
    if (instant) {
      this._lockCells(cells.map(([dr, dc]) => [targetRow + dr, col + dc]));
    } else {
      const startRow = Math.max(0, targetRow - MAX_FALL_ROWS);
      this.currentPiece = { shapeName, cells, col, row: startRow, targetRow };
    }
    return true;
  }

  step() {
    if (this.currentPiece === null) {
      let changed = false;
      while (this.targetFilledCount - this.filledCount > CATCHUP_BUFFER_CELLS) {
        if (!this._advance(true)) break;
        changed = true;
      }
      if (this.filledCount < this.targetFilledCount) {
        if (this._advance(false)) changed = true;
      }
      return changed;
    }

    const piece = this.currentPiece;
    if (piece.row < piece.targetRow) {
      piece.row += 1;
      return true;
    }
    this._lockPiece(piece);
    this.currentPiece = null;
    return true;
  }
}

// Classic DMG (original Game Boy) 4-shade LCD palette -- same as the Python widget.
const COLOR_EMPTY = "#9BBC0F";
const COLOR_ACTIVE = "#8BAC0F";
const COLOR_SETTLED = "#306230";
const COLOR_BORDER = "#0F380F";

class TetrisCanvas {
  constructor(canvasEl, rows = BOARD_ROWS, cols = BOARD_COLS) {
    this.canvas = canvasEl;
    this.ctx = canvasEl.getContext("2d");
    this.model = new TetrisBoardModel(rows, cols);
    this.progressFraction = 0;
    canvasEl.width = cols * DEFAULT_CELL_PX;
    canvasEl.height = rows * DEFAULT_CELL_PX;
  }

  setProgress(fraction) {
    this.progressFraction = Math.max(0, Math.min(1, fraction));
    this.model.setProgress(fraction);
  }

  tick() {
    return this.model.step();
  }

  render() {
    const { ctx, model, canvas } = this;
    const cellW = canvas.width / model.cols;
    const cellH = canvas.height / model.rows;
    ctx.fillStyle = COLOR_BORDER;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    for (let row = 0; row < model.rows; row++) {
      const y = Math.round(row * cellH);
      const h = Math.round((row + 1) * cellH) - y;
      for (let col = 0; col < model.cols; col++) {
        const x = Math.round(col * cellW);
        const w = Math.round((col + 1) * cellW) - x;
        ctx.fillStyle = model.grid[row][col] ? COLOR_SETTLED : COLOR_EMPTY;
        ctx.fillRect(x + 1, y + 1, Math.max(w - 1, 1), Math.max(h - 1, 1));
      }
    }
    const piece = model.currentPiece;
    if (piece !== null) {
      for (const [dr, dc] of piece.cells) {
        const row = piece.row + dr, col = piece.col + dc;
        if (row < 0 || row >= model.rows || col < 0 || col >= model.cols) continue;
        const x = Math.round(col * cellW), w = Math.round((col + 1) * cellW) - x;
        const y = Math.round(row * cellH), h = Math.round((row + 1) * cellH) - y;
        ctx.fillStyle = COLOR_ACTIVE;
        ctx.fillRect(x + 1, y + 1, Math.max(w - 1, 1), Math.max(h - 1, 1));
      }
    }
  }
}

// One shared interval drives every live board, mirroring the Python widget's
// shared-QTimer optimization (N rows, one timer).
const _tetrisInstances = new Set();
let _tetrisTimer = null;

function registerTetrisCanvas(canvasEl) {
  const board = new TetrisCanvas(canvasEl);
  _tetrisInstances.add(board);
  if (_tetrisTimer === null) {
    _tetrisTimer = setInterval(() => {
      for (const b of _tetrisInstances) {
        if (!b.canvas.isConnected) { _tetrisInstances.delete(b); continue; }
        if (b.tick()) b.render();
      }
      if (_tetrisInstances.size === 0) {
        clearInterval(_tetrisTimer);
        _tetrisTimer = null;
      }
    }, ANIMATION_INTERVAL_MS);
  }
  board.render();
  return board;
}
