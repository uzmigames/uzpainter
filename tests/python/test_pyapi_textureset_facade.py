"""Texture-set facade semantics measured by the P22-B channel and texture-set probes."""

from __future__ import annotations

from tests.python.conftest import Run


def test_channel_aliases_share_identity_without_changing_native_api(facade: Run) -> None:
    report = facade(
        """
        aliases = {
            "AbsorptionColor": "TransmissionColor",
            "Anisotropylevel": "SpecularRoughnessAnisotropy",
            "CoatOpacity": "CoatWeight", "Emissive": "EmissionColor",
            "Metallic": "BaseMetalness", "Roughness": "SpecularRoughness",
            "Scattering": "SubsurfaceRadiusScale", "ScatteringColor": "SubsurfaceColor",
            "SheenColor": "FuzzColor", "SheenOpacity": "FuzzWeight",
            "SheenRoughness": "FuzzRoughness", "SpecularEdgeColor": "SpecularColor",
            "Translucency": "SubsurfaceWeight",
        }
        stack = create()
        for alias, canonical in aliases.items():
            member = getattr(CT, alias)
            assert member is getattr(CT, canonical)
            assert CT.__members__[alias] is member
            assert CT(getattr(uzpainter.textureset.ChannelType, alias)) is member
            assert getattr(uzpainter.textureset.ChannelType, alias).name == alias
            if not stack.has_channel(member):
                stack.add_channel(member, ts.ChannelFormat.L16)
            assert stack.get_channel(member).type() is member
            assert raises(stack.add_channel, getattr(CT, canonical), ts.ChannelFormat.L8) == (
                "ValueError: This channel already exists."
            )
        """
    )
    assert report["status"] == "ok", report


def test_channel_edit_clears_omitted_label_and_builtin_labels_are_empty(facade: Run) -> None:
    report = facade(
        """
        stack = create()
        user = stack.add_channel(CT.User14, ts.ChannelFormat.L8, "custom")
        user.edit(ts.ChannelFormat.L16)
        assert user.label() == ""
        stack.edit_channel(CT.User14, ts.ChannelFormat.L32F, "again")
        stack.edit_channel(CT.User14, ts.ChannelFormat.L16)
        assert user.label() == ""
        built_in = stack.add_channel(CT.CoatTangent, ts.ChannelFormat.RGB8, "ignored")
        assert built_in.label() == ""
        built_in.edit(ts.ChannelFormat.RGB16, "also ignored")
        assert built_in.label() == ""
        for operation in (stack.get_channel, stack.remove_channel):
            assert raises(operation, CT.User31) == (
                "ValueError: There is no channel 'user31' in the texture set 'uzp_plane'."
            )
        """
    )
    assert report["status"] == "ok", report


def test_texture_set_string_properties_and_description_survive_reopen(facade: Run) -> None:
    report = facade(
        """
        material = create().material()
        assert isinstance(material.name, str) and callable(material.name)
        assert material.name == material.name() == "uzp_plane"
        assert material.original_name == "uzp_plane" and not callable(material.original_name)
        material.description = "persistent texture-set description"
        assert isinstance(material.description, str) and not callable(material.description)
        path = os.path.join(WORK, "described.spp")
        project.save_as(path)
        project.close()
        project.open(path)
        assert ts.TextureSet.from_name("uzp_plane").description == (
            "persistent texture-set description"
        )
        assert raises(ts.TextureSet.from_name, "other") == (
            "ValueError: Texture Set 'other' not found."
        )
        assert raises(ts.get_active_stack().material().set_resolution, ts.Resolution(300, 300)) == (
            "ValueError: 300 is not a power of two. The resolution must be power of two "
            "and in the range [128,4096]. The available resolutions are 128,256,512,1024,2048."
        )
        """
    )
    assert report["status"] == "ok", report
