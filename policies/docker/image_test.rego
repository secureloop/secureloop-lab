package docker_test

import data.docker
import future.keywords.if

# Test: Valid image should pass without warnings
test_valid_image if {
	input := [{
		"Config": {
			"User": "spring",
			"Healthcheck": {"Test": ["CMD-SHELL", "curl -f http://localhost:8080/actuator/health || exit 1"]},
			"Labels": {
				"org.opencontainers.image.version": "1.0.0",
				"org.opencontainers.image.source": "https://github.com/org/repo",
				"org.opencontainers.image.revision": "abc123",
			},
			"ExposedPorts": {"8080/tcp": {}},
		},
		"RepoTags": ["eclipse-temurin:21-jre"],
	}]

	count(docker.warn) == 0
}

# Test: Image without user should warn
test_image_without_user if {
	input := [{
		"Config": {
			"Healthcheck": {"Test": ["CMD", "curl"]},
			"Labels": {},
		},
		"RepoTags": ["eclipse-temurin:21-jre"],
	}]

	count(docker.warn) > 0
}

# Test: Image running as root should warn
test_image_as_root if {
	input := [{
		"Config": {
			"User": "root",
			"Healthcheck": {"Test": ["CMD", "curl"]},
			"Labels": {},
		},
		"RepoTags": ["eclipse-temurin:21-jre"],
	}]

	count(docker.warn) > 0
}

# Test: Image with latest tag should warn
test_image_with_latest_tag if {
	input := [{
		"Config": {
			"User": "spring",
			"Healthcheck": {"Test": ["CMD", "curl"]},
			"Labels": {},
		},
		"RepoTags": ["myapp:latest"],
	}]

	count(docker.warn) > 0
}

# Test: Image without healthcheck should warn
test_image_without_healthcheck if {
	input := [{
		"Config": {
			"User": "spring",
			"Labels": {},
		},
		"RepoTags": ["eclipse-temurin:21-jre"],
	}]

	count(docker.warn) > 0
}

# Test: Image with missing labels should warn
test_image_missing_labels if {
	input := [{
		"Config": {
			"User": "spring",
			"Healthcheck": {"Test": ["CMD", "curl"]},
			"Labels": {},
		},
		"RepoTags": ["eclipse-temurin:21-jre"],
	}]

	count(docker.warn) > 0
}

# Test: Image with potential secrets should warn
test_image_with_secrets if {
	input := [{
		"Config": {
			"User": "spring",
			"Healthcheck": {"Test": ["CMD", "curl"]},
			"Labels": {},
			"Env": ["DB_PASSWORD=secret123"],
		},
		"RepoTags": ["eclipse-temurin:21-jre"],
	}]

	count(docker.warn) > 0
}
