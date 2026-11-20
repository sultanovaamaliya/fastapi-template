import pytest
from fastapi.testclient import TestClient

from main import create_app


@pytest.fixture
def client(database_path):
    # Таблица уже создана Alembic в изолированной тестовой базе.
    with TestClient(create_app(database_path)) as test_client:
        yield test_client


def test_create_and_read_task(client):
    assert client.get("/tasks").json() == []
    response = client.post("/tasks", json={"title": "Изучить FastAPI"})
    assert response.status_code == 201
    task = response.json()
    assert task == {"id": 1, "title": "Изучить FastAPI", "done": False}
    assert client.get("/tasks").json() == [task]


@pytest.mark.parametrize("title", ["", "x" * 121, "  " + "x" * 120 + "  ", 42, None])
def test_invalid_title_is_rejected(client, title):
    response = client.post("/tasks", json={"title": title})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "title"]
    assert client.get("/tasks").json() == []


def test_title_at_maximum_length_is_accepted(client):
    response = client.post("/tasks", json={"title": "x" * 120})
    assert response.status_code == 201
    assert len(response.json()["title"]) == 120


@pytest.mark.parametrize("title", ["   ", "\t\n", "  Изучить FastAPI  "])
def test_title_whitespace_is_preserved(client, title):
    response = client.post("/tasks", json={"title": title})
    assert response.status_code == 201
    assert response.json()["title"] == title
    assert client.get("/tasks").json()[0]["title"] == title


def test_missing_title_is_rejected(client):
    assert client.post("/tasks", json={}).status_code == 422
    assert client.get("/tasks").json() == []


def test_extra_creation_fields_are_ignored(client):
    response = client.post("/tasks", json={"title": "Задача", "done": True})
    assert response.status_code == 201
    assert response.json()["done"] is False
    assert client.get("/tasks").json()[0]["done"] is False


def test_update_sets_state_and_filter_selects_tasks(client):
    first = client.post("/tasks", json={"title": "Первая"}).json()
    second = client.post("/tasks", json={"title": "Вторая"}).json()
    url = f"/tasks/{first['id']}"
    for _ in range(2):
        response = client.patch(url, json={"done": True})
        assert response.status_code == 200
        assert response.json() == {**first, "done": True}
    assert client.get("/tasks?done=true").json() == [{**first, "done": True}]
    assert client.get("/tasks?done=false").json() == [second]
    assert [task["id"] for task in client.get("/tasks").json()] == [second["id"], first["id"]]
    assert client.patch(url, json={"done": False}).json()["done"] is False


def test_missing_task_returns_404(client):
    response = client.patch("/tasks/999", json={"done": True})
    assert response.status_code == 404
    assert response.json() == {"detail": "Задача не найдена"}


@pytest.mark.parametrize("task_id", ["abc", "0", "-1"])
def test_path_parameter_is_validated(client, task_id):
    response = client.patch(f"/tasks/{task_id}", json={"done": True})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "task_id"]


@pytest.mark.parametrize("done", ["false", 1, None])
def test_json_done_requires_boolean(client, done):
    task = client.post("/tasks", json={"title": "Проверка boolean"}).json()
    assert client.patch(f"/tasks/{task['id']}", json={"done": done}).status_code == 422
    assert client.get("/tasks").json()[0]["done"] is False


def test_invalid_query_parameter(client):
    response = client.get("/tasks?done=maybe")
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "done"]


def test_invalid_json_is_rejected(client):
    response = client.post("/tasks", content='{"title":', headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert client.get("/tasks").json() == []


def test_database_survives_application_restart(database_path):
    with TestClient(create_app(database_path)) as first_client:
        task = first_client.post("/tasks", json={"title": "Сохраниться"}).json()
    with TestClient(create_app(database_path)) as second_client:
        assert second_client.get("/tasks").json() == [task]


def test_openapi_describes_real_api(client):
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]["/tasks"]) == {"get", "post"}
    assert "201" in schema["paths"]["/tasks"]["post"]["responses"]
    assert "patch" in schema["paths"]["/tasks/{task_id}"]
    assert "TaskCreate" in schema["components"]["schemas"]
    assert client.get("/docs").status_code == 200


def test_get_and_delete_task(client):
    create_response = client.post("/tasks", json={"title": "Купить молоко"})
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    get_response = client.get(f"/tasks/{task_id}")
    assert get_response.status_code == 200
    assert get_response.json()["title"] == "Купить молоко"

    delete_response = client.delete(f"/tasks/{task_id}")
    assert delete_response.status_code == 204
    assert delete_response.content == b""  # Пустое тело

    delete_again = client.delete(f"/tasks/{task_id}")
    assert delete_again.status_code == 404

    get_deleted = client.get(f"/tasks/{task_id}")
    assert get_deleted.status_code == 404

    list_response = client.get("/tasks")
    ids = [task["id"] for task in list_response.json()]
    assert task_id not in ids


def test_unknown_task_id_returns_404(client):
    assert client.get("/tasks/999").status_code == 404
    assert client.delete("/tasks/999").status_code == 404