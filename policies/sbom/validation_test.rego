package sbom_test

import data.sbom
import future.keywords.if

# Test: Valid SBOM should pass without warnings
test_valid_sbom if {
	input := {
		"bomFormat": "CycloneDX",
		"specVersion": "1.5",
		"components": [
			{
				"name": "spring-boot",
				"version": "4.0.0",
				"licenses": [{"license": {"id": "Apache-2.0"}}],
			},
			{
				"name": "jackson-databind",
				"version": "2.15.0",
				"licenses": [{"license": {"id": "Apache-2.0"}}],
			},
		],
	}

	count(sbom.warn) == 0
}

# Test: Missing CycloneDX format should warn
test_missing_format if {
	input := {
		"specVersion": "1.5",
		"components": [],
	}

	count(sbom.warn) > 0
}

# Test: Prohibited license should warn
test_prohibited_license if {
	input := {
		"bomFormat": "CycloneDX",
		"specVersion": "1.5",
		"components": [{
			"name": "gpl-library",
			"version": "1.0.0",
			"licenses": [{"license": {"id": "GPL-3.0"}}],
		}],
	}

	count(sbom.warn) > 0
}

# Test: Missing license should warn
test_missing_license if {
	input := {
		"bomFormat": "CycloneDX",
		"specVersion": "1.5",
		"components": [{
			"name": "unlicensed-lib",
			"version": "1.0.0",
		}],
	}

	count(sbom.warn) > 0
}

# Test: Incomplete SBOM (< 5 components) should warn
test_incomplete_sbom if {
	input := {
		"bomFormat": "CycloneDX",
		"specVersion": "1.5",
		"components": [
			{"name": "lib1", "version": "1.0.0", "licenses": [{"license": {"id": "MIT"}}]},
			{"name": "lib2", "version": "2.0.0", "licenses": [{"license": {"id": "Apache-2.0"}}]},
		],
	}

	count(sbom.warn) > 0
}
