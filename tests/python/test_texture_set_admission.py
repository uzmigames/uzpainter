"""CPU-only worker budget fixtures exercise native project mutations, without a GPU."""

from __future__ import annotations

from tests.python.conftest import Run


def test_creation_budget_refusal_and_cpu_metadata_without_budget(run: Run) -> None:
    report = run("""
        import uzp_job_test as fixture
        fixture.admission_limits(0, 0)
        error = raises(create)
        assert error and "texture_set_over_budget" in error, error
        assert not project.is_open()
        fixture.admission_limits(None, 0)
        stack = create()
        assert project.is_open()
        fixture.admission_limits(64 << 20, 0)
        before = project.revision()
        error = raises(stack.material().set_resolution, ts.Resolution(512, 512))
        assert error and "descriptor budget" in error, error
        assert project.revision() == before
        assert stack.material().get_resolution().width == 256
        channels = stack.all_channels()
        fixture.admission_limits(64 << 20, len(channels) + 3)
        error = raises(stack.add_channel, CT.User0, ts.ChannelFormat.L16)
        assert error and "descriptor budget" in error, error
        assert not stack.has_channel(CT.User0)
        assert project.revision() == before
        fixture.admission_limits(None, 0)
        project.close()
    """)
    assert report["status"] == "ok", report


def test_resize_budget_is_atomic_and_explicit_transaction_checks_final_state(run: Run) -> None:
    report = run("""
        import uzp_job_test as fixture
        fixture.admission_limits(64 << 20, 1000000)
        stack = create()
        tset = stack.material()
        before = project.revision()
        error = raises(tset.set_resolution, ts.Resolution(8192, 8192))
        assert error and "texture_set_over_budget" in error, error
        assert project.revision() == before
        assert tset.get_resolution().width == 256
        error = raises(ts.set_resolutions, [tset], ts.Resolution(8192, 8192))
        assert error and "texture_set_over_budget" in error, error
        assert project.revision() == before
        assert tset.get_resolution().width == 256
        try:
            with uzpainter.Transaction("refused final size"):
                tset.set_resolution(ts.Resolution(8192, 8192))
                assert tset.get_resolution().width == 8192
        except RuntimeError as error:
            assert "texture_set_over_budget" in str(error), error
        else:
            raise AssertionError("over-budget transaction committed")
        assert project.revision() == before
        assert tset.get_resolution().width == 256
        with uzpainter.Transaction("temporary oversize"):
            tset.set_resolution(ts.Resolution(8192, 8192))
            tset.set_resolution(ts.Resolution(512, 512))
        assert project.revision() == before + 1
        assert tset.get_resolution().width == 512
        fixture.admission_limits(None, 0)
        tset.set_resolution(ts.Resolution(8192, 8192))
        assert tset.get_resolution().width == 8192
        project.close()
    """)
    assert report["status"] == "ok", report
