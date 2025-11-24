# Gitlab Setup

## Runner

```aiignore
docker run -d --name gitlab-runner --restart always \
-v /srv/gitlab-runner/config:/etc/gitlab-runner \
-v /var/run/docker.sock:/var/run/docker.sock \
gitlab/gitlab-runner:v18.6.1
```

```
docker exec -it gitlab-runner gitlab-runner register  --url https://gitlab.secureloop.de  --token <YOUR_TOKEN>
```