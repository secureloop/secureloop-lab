package maven_test

import data.maven
import future.keywords.if

# Test: Valid POM should pass without warnings
test_valid_pom if {
	input := {
		"project": {
			"groupId": "de.secureloop.demo",
			"artifactId": "spring-demo",
			"version": "1.0.0",
			"description": "Demo Spring Boot application",
			"parent": {
				"artifactId": "spring-boot-starter-parent",
				"version": "4.0.0",
			},
			"properties": {"java.version": "21"},
			"build": {"plugins": [
				{"artifactId": "spring-boot-maven-plugin"},
				{"artifactId": "cyclonedx-maven-plugin"},
			]},
			"licenses": [{"name": "Apache-2.0"}],
		},
		"metadata": {"branch": "develop"},
	}

	count(maven.warn) == 0
}

# Test: Invalid version format should warn
test_invalid_version if {
	input := {
		"project": {
			"groupId": "de.secureloop.demo",
			"version": "1.0",
			"properties": {"java.version": "21"},
			"build": {"plugins": []},
		},
		"metadata": {"branch": "develop"},
	}

	count(maven.warn) > 0
}

# Test: SNAPSHOT on main branch should warn
test_snapshot_on_main if {
	input := {
		"project": {
			"groupId": "de.secureloop.demo",
			"version": "1.0.0-SNAPSHOT",
			"properties": {"java.version": "21"},
			"build": {"plugins": []},
		},
		"metadata": {"branch": "main"},
	}

	count(maven.warn) > 0
}

# Test: Wrong groupId should warn
test_wrong_groupid if {
	input := {
		"project": {
			"groupId": "com.example",
			"version": "1.0.0",
			"properties": {"java.version": "21"},
			"build": {"plugins": []},
		},
		"metadata": {"branch": "develop"},
	}

	count(maven.warn) > 0
}

# Test: Wrong Java version should warn
test_wrong_java_version if {
	input := {
		"project": {
			"groupId": "de.secureloop.demo",
			"version": "1.0.0",
			"properties": {"java.version": "17"},
			"build": {"plugins": []},
		},
		"metadata": {"branch": "develop"},
	}

	count(maven.warn) > 0
}

# Test: Missing required plugins should warn
test_missing_plugins if {
	input := {
		"project": {
			"groupId": "de.secureloop.demo",
			"version": "1.0.0",
			"properties": {"java.version": "21"},
			"build": {"plugins": [{"artifactId": "spring-boot-maven-plugin"}]},
		},
		"metadata": {"branch": "develop"},
	}

	count(maven.warn) > 0
}

# Test: Missing license should warn
test_missing_license if {
	input := {
		"project": {
			"groupId": "de.secureloop.demo",
			"version": "1.0.0",
			"properties": {"java.version": "21"},
			"build": {"plugins": []},
		},
		"metadata": {"branch": "develop"},
	}

	count(maven.warn) > 0
}
