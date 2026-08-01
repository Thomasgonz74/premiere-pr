import random

from torrent2000.ui.widgets.tetris_progress import (
    CATCHUP_BUFFER_CELLS,
    MAX_FALL_ROWS,
    TetrisBoardModel,
)


def run_until_idle(model: TetrisBoardModel, max_ticks: int = 100_000) -> int:
    ticks = 0
    while model.step():
        ticks += 1
        if ticks > max_ticks:
            raise AssertionError("model never settled -- possible infinite loop")
    return ticks


def all_cells(model: TetrisBoardModel):
    for row in range(model.rows):
        for col in range(model.cols):
            yield row, col


def empty_count(model: TetrisBoardModel) -> int:
    return sum(1 for r, c in all_cells(model) if not model.grid[r][c])


def test_empty_board_at_zero_progress():
    model = TetrisBoardModel(rows=4, cols=4)
    model.set_progress(0.0)
    assert model.filled_count == 0
    assert empty_count(model) == model.total_cells


def test_set_progress_never_mutates_board_synchronously():
    model = TetrisBoardModel(rows=8, cols=18)
    model.set_progress(0.9)
    # set_progress only ever updates the target; nothing should have moved.
    assert model.filled_count == 0
    assert model.current_piece is None
    assert model.target_filled_count == round(0.9 * model.total_cells)


def test_full_board_at_full_progress_after_settling():
    # Run several random seeds: the guaranteed-completion behavior must hold
    # regardless of which random pieces happened to drop along the way.
    for seed in range(5):
        random.seed(seed)
        model = TetrisBoardModel(rows=8, cols=18)
        model.set_progress(1.0)
        run_until_idle(model)
        assert model.is_full()
        assert model.filled_count == model.total_cells
        assert empty_count(model) == 0
        assert all(all(row) for row in model.grid)


def test_full_board_at_full_progress_non_multiple_of_four():
    # 25 cells -- not a multiple of CELLS_PER_PIECE -- exercises the tail
    # accounting when the last piece can't fully fit under the target cap.
    random.seed(7)
    model = TetrisBoardModel(rows=5, cols=5)
    model.set_progress(1.0)
    run_until_idle(model)
    assert model.is_full()
    assert model.filled_count == model.total_cells == 25
    assert empty_count(model) == 0


def test_varied_tetromino_shapes_are_used_across_many_spawns():
    # (a) More than one distinct shape must appear -- not the same shape
    # repeated forever. Progress increments gradually (staying under the
    # catch-up buffer) so pieces animate one at a time and their shape can be
    # observed via current_piece rather than being absorbed into an instant
    # catch-up lock.
    random.seed(1)
    model = TetrisBoardModel(rows=8, cols=18)
    shapes_seen = set()
    fraction = 0.0
    step_fraction = (CATCHUP_BUFFER_CELLS // 2) / model.total_cells
    for _ in range(15):
        fraction = min(1.0, fraction + step_fraction)
        model.set_progress(fraction)
        seen_this_piece = None
        while model.step():
            piece = model.current_piece
            if piece is not None and piece is not seen_this_piece:
                shapes_seen.add(piece.shape_name)
                seen_this_piece = piece
    assert len(shapes_seen) > 1


def test_holes_appear_during_normal_play_on_a_large_board():
    # (b) At an intermediate progress on a large-enough board, real gravity
    # must have trapped at least one hole (an empty cell with an occupied
    # cell above it in the same column) -- the whole point of switching to
    # real physics instead of a rigid fill order.
    found_hole = False
    for seed in range(10):
        random.seed(seed)
        model = TetrisBoardModel(rows=8, cols=18)
        model.set_progress(0.45)
        run_until_idle(model)
        for col in range(model.cols):
            seen_occupied = False
            for row in range(model.rows):
                if model.grid[row][col]:
                    seen_occupied = True
                elif seen_occupied:
                    found_hole = True
                    break
            if found_hole:
                break
        if found_hole:
            break
    assert found_hole, "expected at least one trapped hole across several random seeds"


def test_never_exceeds_target_mid_animation():
    # (d) filled_count must never exceed target_filled_count at any point,
    # for any board state reachable during stepping.
    random.seed(3)
    model = TetrisBoardModel(rows=8, cols=18)
    model.set_progress(0.3)
    for _ in range(1000):
        model.step()
        assert model.filled_count <= model.target_filled_count
        piece = model.current_piece
        if piece is not None:
            for row, col in piece.cells_on_board():
                assert 0 <= row < model.rows
                assert 0 <= col < model.cols


def test_catchup_never_overshoots_target():
    random.seed(4)
    model = TetrisBoardModel(rows=8, cols=18)
    model.set_progress(0.8)
    for _ in range(500):
        model.step()
        assert model.filled_count <= model.target_filled_count


def test_progress_can_increase_after_settling():
    random.seed(5)
    model = TetrisBoardModel(rows=8, cols=18)
    model.set_progress(0.25)
    run_until_idle(model)
    assert model.filled_count == round(0.25 * model.total_cells)

    model.set_progress(0.75)
    run_until_idle(model)
    assert model.filled_count == round(0.75 * model.total_cells)


def test_piece_fall_distance_is_capped_on_tall_boards():
    # Even though placement is random (a piece can land anywhere, not just
    # near the floor), a single piece's visible fall animation is still
    # bounded to MAX_FALL_ROWS ticks so it never takes a long time to
    # visually resolve, no matter how far its target row is from row 0.
    random.seed(2)
    model = TetrisBoardModel(rows=20, cols=10)
    model.set_progress(1 / model.total_cells)  # first piece placed on an empty board
    model.step()  # spawn
    piece = model.current_piece
    assert piece is not None
    fall_distance = piece.target_row - piece.row
    assert fall_distance <= MAX_FALL_ROWS

    ticks_to_land = 0
    while model.current_piece is not None:
        model.step()
        ticks_to_land += 1
    assert ticks_to_land == fall_distance + 1


def test_placement_is_scattered_not_gravity_biased_toward_the_floor():
    # This is the actual fix being tested: pieces used to always drop via
    # gravity onto the top of the existing per-column stack, so an empty
    # board's first several pieces always landed near the floor -- reading
    # as "filling by line" rather than random. Placement is now chosen
    # uniformly among every valid spot on the board, so across many spawns
    # on a tall, otherwise-empty board, target rows should spread out
    # instead of clustering near the bottom.
    random.seed(3)
    model = TetrisBoardModel(rows=20, cols=10)
    target_rows = []
    for _ in range(15):
        model.current_piece = None
        placement = model._find_placement()
        assert placement is not None
        _, _, _, target_row = placement
        target_rows.append(target_row)

    near_floor = sum(1 for r in target_rows if r >= model.rows - 4)
    assert near_floor < len(target_rows)  # not every piece hugs the floor
    assert min(target_rows) < model.rows // 2  # some pieces land in the upper half


def test_large_backlog_catches_up_quickly():
    # (e) A large jump in target (e.g. resuming a torrent already at 80%)
    # must be absorbed in a handful of ticks, not hundreds.
    random.seed(6)
    model = TetrisBoardModel(rows=8, cols=18)  # 144 cells total
    model.set_progress(0.8)  # resumed torrent already mostly done
    ticks = 0
    while model.target_filled_count - model.filled_count > CATCHUP_BUFFER_CELLS:
        assert model.step()
        ticks += 1
        assert ticks < 50
    backlog = model.target_filled_count - model.filled_count
    assert backlog <= CATCHUP_BUFFER_CELLS
    # the remaining buffer still animates piece by piece, not instantly
    assert model.filled_count < model.target_filled_count or model.current_piece is not None


def test_large_backlog_absorbed_in_a_single_step_call():
    random.seed(8)
    model = TetrisBoardModel(rows=8, cols=18)
    model.set_progress(0.8)
    model.step()  # a single tick should absorb everything beyond the buffer
    backlog = model.target_filled_count - model.filled_count
    assert backlog <= CATCHUP_BUFFER_CELLS


def test_set_progress_clamps_out_of_range_values():
    model = TetrisBoardModel(rows=4, cols=4)
    model.set_progress(-0.5)
    assert model.target_filled_count == 0
    model.set_progress(1.5)
    assert model.target_filled_count == model.total_cells


def test_tiny_torrent_finishes_completely_and_quickly():
    # A very small board (e.g. a tiny torrent) must still be able to reach a
    # fully solid state without pathological behavior.
    random.seed(9)
    model = TetrisBoardModel(rows=4, cols=4)
    model.set_progress(1.0)
    ticks = run_until_idle(model)
    assert model.is_full()
    assert ticks < 200
