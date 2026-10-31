"""Regression tests for CSV records with list-valued columns."""
import json

from boom_birds.evaluation.csv_io import read_rows_csv, write_rows_csv


def test_list_columns_round_trip(tmp_path):
    path = tmp_path / 'rows.csv'
    columns = ['scenario', 'step', 'position_world_m', 'velocity_world_mps',
               'env_terminated', 'env_truncated']
    rows = [{'scenario': 'hover_trim', 'step': 0,
             'position_world_m': [0.0, 1.5, 0.75],
             'velocity_world_mps': [0.0, 0.0, 0.01],
             'env_terminated': False, 'env_truncated': False}]
    write_rows_csv(path, columns, rows)
    loaded = read_rows_csv(path)
    assert len(loaded) == 1
    assert json.loads(loaded[0]['position_world_m']) == [0.0, 1.5, 0.75]
    assert json.loads(loaded[0]['velocity_world_mps']) == [0.0, 0.0, 0.01]
    assert loaded[0]['env_terminated'] == 'False'
    assert loaded[0]['scenario'] == 'hover_trim'
