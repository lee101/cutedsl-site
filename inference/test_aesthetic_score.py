import torch

from aesthetic_score import AestheticHead, _remap_head_state_dict


def test_head_forward_shape():
    head = AestheticHead()
    out = head(torch.randn(3, 768))
    assert out.shape == (3, 1)


def test_remap_accepts_prefixed_and_bare_keys():
    head = AestheticHead()
    state = head.state_dict()
    assert _remap_head_state_dict(state).keys() == state.keys()
    bare = {k.removeprefix("layers."): v for k, v in state.items()}
    remapped = _remap_head_state_dict(bare)
    head.load_state_dict(remapped)


def test_score_images_none_when_disabled(monkeypatch):
    import aesthetic_score as a

    monkeypatch.setattr(a, "AESTHETIC_ENABLED", False)
    monkeypatch.setattr(a, "_scorer", None)
    assert a.score_images([]) is None
