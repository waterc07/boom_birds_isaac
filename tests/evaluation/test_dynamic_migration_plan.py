from pathlib import Path

import pytest

from boom_birds.evaluation import dynamic_migration_plan as plans


def setup(root):
    (root / 'src').mkdir()
    (root / 'src' / 'entry.py').write_text('original', encoding='utf-8')
    (root / 'scripts').mkdir()
    (root / 'scripts' / 'run_dynamic_eval.py').write_text('runner', encoding='utf-8')
    for name in ('cases.json', 'map.yaml', 'vehicle.yaml'):
        (root / name).write_text('{}', encoding='utf-8')
    return {'cases': Path('cases.json'), 'map_config': Path('map.yaml'),
            'vehicle_config': Path('vehicle.yaml'), 'output': 'first',
            'geometry_policy': 'reference_origin_v2', 'contact_mode': 'measured_hard_reset'}


def test_source_changes_in_dirty_worktree_are_rejected(tmp_path):
    args = setup(tmp_path)
    freeze = plans.build_migration_freeze(args, tmp_path)
    (tmp_path / 'src' / 'entry.py').write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='source'):
        plans.validate_migration_freeze(freeze, args, tmp_path)


def test_run_parameter_changes_are_rejected(tmp_path):
    args = setup(tmp_path)
    freeze = plans.build_migration_freeze(args, tmp_path)
    args['contact_mode'] = 'legacy_inference'
    with pytest.raises(ValueError, match='parameter'):
        plans.validate_migration_freeze(freeze, args, tmp_path)


def test_config_changes_are_rejected(tmp_path):
    args = setup(tmp_path)
    freeze = plans.build_migration_freeze(args, tmp_path)
    (tmp_path / 'cases.json').write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='config'):
        plans.validate_migration_freeze(freeze, args, tmp_path)


def test_output_directory_can_change_without_changing_the_experiment(tmp_path):
    args = setup(tmp_path)
    freeze = plans.build_migration_freeze(args, tmp_path)
    args['output'] = 'second'
    plans.validate_migration_freeze(freeze, args, tmp_path)
