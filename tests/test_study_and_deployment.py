from pathlib import Path
import csv
import importlib.util
import json
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/"scripts"/(name+".py"))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_annotation_scoring_refuses_blank_or_incomplete_labels(tmp_path):
    scorer=load_script("score_annotations")
    path=tmp_path/"blank.csv"
    path.write_text("id,sentiment,complaint,aspects\none,,,,\n",encoding="utf8")
    with pytest.raises(ValueError,match="blank labels"):
        scorer.read_sheet(path)


def test_import_redacts_common_identifiers_without_inventing_ratings():
    importer=load_script("import_nhtsa")
    result=importer.redact("VIN 1HGCM82633A004352; mail owner@example.com; call 555-123-4567")
    assert "1HGCM82633A004352" not in result
    assert "owner@example.com" not in result
    assert "555-123-4567" not in result


def test_container_boundary_keeps_source_data_readonly_and_api_unpublished():
    compose=yaml.safe_load((ROOT/"docker-compose.yml").read_text())
    api=compose["services"]["api"];dashboard=compose["services"]["dashboard"]
    assert not api.get("ports")
    assert api["environment"]["DRIVESENSE_ACCESS_MODE"]=="shared"
    assert any(v.endswith(":ro") for v in api["volumes"])
    assert api["environment"]["DRIVESENSE_DB_PATH"].startswith("/app/state/")
    assert all(p.startswith("127.0.0.1:") for p in dashboard["ports"])
    assert dashboard["depends_on"]["api"]["condition"]=="service_healthy"


def test_locked_frontend_dependencies_match_lockfile():
    package=json.loads((ROOT/"frontend/package.json").read_text())
    lock=json.loads((ROOT/"frontend/package-lock.json").read_text())
    assert all(version==lock["packages"]["node_modules/"+name]["version"] for name,version in package["dependencies"].items())
