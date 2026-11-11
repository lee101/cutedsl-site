import unittest

from scripts.validate_static_deploy_config import validate_static_deploy_config


class StaticDeployConfigTest(unittest.TestCase):
    def test_accepts_url_matching_r2_upload_prefix(self) -> None:
        validate_static_deploy_config(
            "https://appstatic.app.nz/cutedsl/static", "cutedsl", "static"
        )

    def test_rejects_legacy_base_that_omits_static_prefix(self) -> None:
        with self.assertRaisesRegex(ValueError, "assets are uploaded under"):
            validate_static_deploy_config(
                "https://appstatic.app.nz/cutedsl", "cutedsl", "static"
            )

    def test_allows_custom_domain_with_non_identity_path_mapping(self) -> None:
        validate_static_deploy_config(
            "https://cutedslstatic.cutedsl.cc", "cutedsl", "static"
        )


if __name__ == "__main__":
    unittest.main()
