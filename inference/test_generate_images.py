import threading

from scripts import generate_images


def test_concurrent_generation_is_bounded_ordered_and_failure_isolated(monkeypatch):
    active = 0
    max_active = 0
    lock = threading.Lock()
    first_pair_started = threading.Barrier(2)

    def generate(prompt, _width, _height, _steps):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            if prompt in {"first", "broken"}:
                first_pair_started.wait(timeout=2)
            if prompt == "broken":
                raise RuntimeError("one request failed")
            return {"prompt": prompt}, None
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(generate_images, "generate_image_with_quality_retry", generate)

    submitted = []
    results = list(
        generate_images.iter_generation_results(
            ["first", "broken", "third"],
            width=256,
            height=256,
            steps=4,
            concurrency=2,
            on_submit=lambda index, prompt: submitted.append((index, prompt)),
        )
    )

    assert submitted == [(0, "first"), (1, "broken"), (2, "third")]
    assert [index for index, _prompt, _result in results] == [0, 1, 2]
    assert [prompt for _index, prompt, _result in results] == [
        "first",
        "broken",
        "third",
    ]
    assert max_active == 2
    assert results[0][2] == ({"prompt": "first"}, None, None)
    assert isinstance(results[1][2][2], RuntimeError)
    assert results[2][2] == ({"prompt": "third"}, None, None)
