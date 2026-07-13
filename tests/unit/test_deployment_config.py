from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_systemd_service_runs_unprivileged_on_loopback():
    service = (ROOT / "agent-nexus.service").read_text(encoding="utf-8")

    assert "User=ubuntu" in service
    assert "Group=ubuntu" in service
    assert "Environment=NEXUS_DB_PATH=/home/ubuntu/.nexus/agent-nexus-prod.db" in service
    assert "Environment=EXEC_USER=tencent" in service
    assert "--host 127.0.0.1" in service
    assert "--port 8081" in service
    assert "NoNewPrivileges=true" in service
    assert "PrivateTmp=true" in service
    assert "ProtectSystem=full" in service
    assert "--host 0.0.0.0" not in service


def test_nginx_exposes_port_80_and_proxies_streaming_connections():
    nginx = (ROOT / "deploy/nginx-agent-nexus.conf").read_text(encoding="utf-8")

    assert "listen 80 default_server;" in nginx
    assert "proxy_pass http://127.0.0.1:8081;" in nginx
    assert "proxy_http_version 1.1;" in nginx
    assert 'proxy_set_header Connection "upgrade";' in nginx
    assert "proxy_buffering off;" in nginx
