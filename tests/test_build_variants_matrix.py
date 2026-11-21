#!/usr/bin/env python3
"""
Unit tests for multi-dimension flavor matrix, buildTypes parsing,
BuildVariantInfo generation, variant menu selection, APK finding, and package detection.
"""

import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from core import ui
from core.config import ConfigManager
from core.gradle import (
    get_flavor_dimensions,
    get_product_flavors,
    get_build_types,
    get_flavor_combinations,
    get_build_variants,
    resolve_target_variants,
)
from core.apk_finder import find_best_apk
from core.package_detector import get_package_from_gradle
from commands.cmd_build import run_build
from commands.cmd_flavor import run_flavor


KTS_MATRIX_GRADLE = """
plugins {
    id("com.android.application")
}

android {
    namespace = "com.example.ghi"

    defaultConfig {
        applicationId = "com.example.ghi"
    }

    buildTypes {
        // comment about release
        release {
            isMinifyEnabled = true
        }
        /*
        create("commentedOut") {
            applicationIdSuffix = ".fake"
        }
        */
        create("staging") {
            initWith(getByName("debug"))
            applicationIdSuffix = ".staging"
        }
    }

    flavorDimensions += listOf("edition", "distribution")
    productFlavors {
        create("global") {
            dimension = "edition"
        }
        create("vietnamese") {
            dimension = "edition"
            applicationIdSuffix = ".vi"
        }
        create("gplay") {
            dimension = "distribution"
        }
        create("direct") {
            dimension = "distribution"
        }
    }
}
"""

GROOVY_MATRIX_GRADLE = """
android {
    defaultConfig {
        applicationId "com.example.groovy"
    }
    flavorDimensions "tier", "store"
    productFlavors {
        free {
            dimension "tier"
            applicationIdSuffix ".free"
        }
        paid {
            dimension "tier"
        }
        google {
            dimension "store"
        }
        samsung {
            dimension "store"
        }
    }
    buildTypes {
        debug {
            applicationIdSuffix ".debug"
        }
        release {
            minifyEnabled true
        }
    }
}
"""


class TestBuildVariantsMatrix(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.app_dir = self.temp_dir / "app"
        self.app_dir.mkdir(parents=True)
        (self.temp_dir / "settings.gradle.kts").write_text('include(":app")\n', encoding="utf-8")
        self._prev_instance = ConfigManager._instance
        ConfigManager._instance = ConfigManager(self.temp_dir)

    def tearDown(self):
        ConfigManager._instance = self._prev_instance
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_kotlin_dsl_matrix_and_build_types(self):
        (self.app_dir / "build.gradle.kts").write_text(KTS_MATRIX_GRADLE, encoding="utf-8")

        dims = get_flavor_dimensions(":app")
        self.assertEqual(dims, ["edition", "distribution"])

        raw_flavors = get_product_flavors(":app")
        self.assertEqual([f.name for f in raw_flavors], ["global", "vietnamese", "gplay", "direct"])

        bts = get_build_types(":app")
        self.assertEqual([bt.name for bt in bts], ["debug", "staging", "release"])
        self.assertEqual(bts[1].application_id_suffix, ".staging")

        combos = get_flavor_combinations(":app")
        self.assertEqual(
            [c.name for c in combos],
            ["globalGplay", "globalDirect", "vietnameseGplay", "vietnameseDirect"],
        )
        self.assertEqual(combos[0].application_id_suffix, "")
        self.assertEqual(combos[2].application_id_suffix, ".vi")

        variants = get_build_variants(":app")
        self.assertEqual(len(variants), 12)  # 4 flavor combos x 3 build types
        self.assertEqual(
            [v.name for v in variants],
            [
                "globalGplayDebug",
                "globalDirectDebug",
                "vietnameseGplayDebug",
                "vietnameseDirectDebug",
                "globalGplayStaging",
                "globalDirectStaging",
                "vietnameseGplayStaging",
                "vietnameseDirectStaging",
                "globalGplayRelease",
                "globalDirectRelease",
                "vietnameseGplayRelease",
                "vietnameseDirectRelease",
            ],
        )
        self.assertEqual(variants[0].gradle_task, "assembleGlobalGplayDebug")
        self.assertEqual(variants[7].gradle_task, "assembleVietnameseDirectStaging")
        self.assertEqual(variants[11].gradle_task, "assembleVietnameseDirectRelease")

    def test_parse_groovy_dsl_matrix_and_suffix_composition(self):
        (self.app_dir / "build.gradle").write_text(GROOVY_MATRIX_GRADLE, encoding="utf-8")

        variants = get_build_variants(":app")
        self.assertEqual(len(variants), 8)
        self.assertEqual(variants[0].name, "freeGoogleDebug")
        self.assertEqual(variants[0].gradle_task, "assembleFreeGoogleDebug")
        self.assertEqual(variants[0].application_id_suffix, ".free.debug")

        pkg = get_package_from_gradle(flavor="freeGoogle", module=":app", variant="debug")
        self.assertEqual(pkg, "com.example.groovy.free.debug")

        pkg_rel = get_package_from_gradle(flavor="freeGoogle", module=":app", variant="release")
        self.assertEqual(pkg_rel, "com.example.groovy.free")

    def test_resolve_target_variants_menu_default_first_and_presets(self):
        (self.app_dir / "build.gradle.kts").write_text(KTS_MATRIX_GRADLE, encoding="utf-8")

        # Default Enter ('') picks [1] (globalGplayDebug), NOT overwriting debug+release
        with patch("builtins.input", return_value=""):
            selected = resolve_target_variants(module=":app")
            self.assertEqual([v.name for v in selected], ["globalGplayDebug"])

        # 'd' preset selects all 4 debug variants
        with patch("builtins.input", return_value="d"):
            selected = resolve_target_variants(module=":app")
            self.assertEqual(
                [v.name for v in selected],
                ["globalGplayDebug", "globalDirectDebug", "vietnameseGplayDebug", "vietnameseDirectDebug"],
            )

        # 'a' selects all 12 variants
        with patch("builtins.input", return_value="a"):
            selected = resolve_target_variants(module=":app")
            self.assertEqual(len(selected), 12)

        # Comma-separated cross-type selection
        with patch("builtins.input", return_value="3, 12"):
            selected = resolve_target_variants(module=":app")
            self.assertEqual([v.name for v in selected], ["vietnameseGplayDebug", "vietnameseDirectRelease"])

    def test_resolve_target_variants_cli_filters(self):
        (self.app_dir / "build.gradle.kts").write_text(KTS_MATRIX_GRADLE, encoding="utf-8")

        # -v release filters to 4 release variants only
        with patch("builtins.input", return_value="2"):
            selected = resolve_target_variants(module=":app", variant_arg="release")
            self.assertEqual([v.name for v in selected], ["globalDirectRelease"])

        # -f vietnameseDirect runs vietnameseDirectDebug directly without prompting
        selected = resolve_target_variants(module=":app", flavor_arg="vietnameseDirect")
        self.assertEqual([v.name for v in selected], ["vietnameseDirectDebug"])

        # -f vietnameseDirectRelease matches full variant name directly
        selected = resolve_target_variants(module=":app", flavor_arg="vietnameseDirectRelease")
        self.assertEqual([v.name for v in selected], ["vietnameseDirectRelease"])

        # -f global (partial dimension) prompts only globalGplayDebug and globalDirectDebug
        with patch("builtins.input", return_value="2"):
            selected = resolve_target_variants(module=":app", flavor_arg="global")
            self.assertEqual([v.name for v in selected], ["globalDirectDebug"])

    def test_simple_project_skips_menu(self):
        simple_gradle = """
        android {
            defaultConfig { applicationId = "com.example.simple" }
        }
        """
        (self.app_dir / "build.gradle.kts").write_text(simple_gradle, encoding="utf-8")

        selected = resolve_target_variants(module=":app")
        self.assertEqual([v.name for v in selected], ["debug"])
        self.assertEqual(selected[0].gradle_task, "assembleDebug")

    def test_find_best_apk_multi_dimension_hyphen_or_camel(self):
        apk_gplay = self.app_dir / "build/outputs/apk/globalGplay/debug/app-global-gplay-debug.apk"
        apk_direct = self.app_dir / "build/outputs/apk/globalDirect/debug/app-global-direct-debug.apk"
        apk_gplay.parent.mkdir(parents=True)
        apk_direct.parent.mkdir(parents=True)
        apk_gplay.write_bytes(b"gplay")
        apk_direct.write_bytes(b"direct")
        # Make globalDirect newer than globalGplay to verify filtering isn't fooled by mtime
        os.utime(apk_gplay, (1000, 1000))
        os.utime(apk_direct, (2000, 2000))

        found = find_best_apk(variant="debug", module=":app", flavor="globalGplay")
        self.assertEqual(found.resolve(), apk_gplay.resolve())

    @patch("commands.cmd_build.execute_gradle")
    def test_run_build_selected_matrix_variant(self, mock_gradle):
        (self.app_dir / "build.gradle.kts").write_text(KTS_MATRIX_GRADLE, encoding="utf-8")
        mock_gradle.return_value = MagicMock(returncode=0)

        apk_path = self.app_dir / "build/outputs/apk/vietnameseDirect/staging/app-vietnamese-direct-staging.apk"
        apk_path.parent.mkdir(parents=True)
        apk_path.write_bytes(b"apk")

        with patch("builtins.input", return_value="8"):  # vietnameseDirectStaging
            run_build(module=":app")

        mock_gradle.assert_called_once_with("assembleVietnameseDirectStaging", module=":app", extra_args=[])

    def test_run_flavor_select_matrix_combo(self):
        (self.app_dir / "build.gradle.kts").write_text(KTS_MATRIX_GRADLE, encoding="utf-8")
        run_flavor(action="select", flavor_name="vietnameseDirect")
        self.assertEqual(ConfigManager.get_instance().get_selected_flavor(), "vietnameseDirect")


if __name__ == "__main__":
    unittest.main()
