from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import wait_for


def test_create_and_download_film(manager):
    client = TestClient(create_app(manager))
    assert "Studio de films IA" in client.get("/").text

    response = client.post("/api/films", json={"idea": "Un robot jardinier", "num_scenes": 2})
    assert response.status_code == 202
    job_id = response.json()["id"]
    wait_for(manager, job_id)

    film = client.get(f"/api/films/{job_id}").json()
    assert film["status"] == "done"
    video = client.get(film["video_url"])
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4"
    assert client.get(film["subtitles_url"]).status_code == 200
    assert [f["id"] for f in client.get("/api/films").json()] == [job_id]

    assert client.get(f"/films/{job_id}/job.json").status_code == 404
    assert client.delete(f"/api/films/{job_id}").status_code == 204
    assert client.get(f"/api/films/{job_id}").status_code == 404


def test_validation_and_replicate_requirement(manager):
    client = TestClient(create_app(manager))
    assert client.post("/api/films", json={"idea": "x"}).status_code == 422
    assert client.post("/api/films", json={"idea": "Un robot", "num_scenes": 40}).status_code == 422
    response = client.post("/api/films", json={"idea": "Un robot", "visual_mode": "video"})
    assert response.status_code == 400
    assert client.get("/api/config").json()["replicate"] is False
