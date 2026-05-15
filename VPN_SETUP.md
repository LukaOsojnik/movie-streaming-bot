# VPN Setup — Gluetun + qBittorrent (NordVPN WireGuard)

qBittorrent now runs inside Docker, sharing the network namespace of a `gluetun`
container. All BitTorrent traffic exits via NordVPN. `movie-bot` and
`cloudflared` are unchanged on host networking and reach the WebUI on
`127.0.0.1:8080` (published by gluetun, host-only).

## One-time setup

### 1. Stop the host qBittorrent

```
pkill qbittorrent
```

Wait for it to shut down cleanly. If you want to keep in-progress torrents,
copy `~/.local/share/qBittorrent/BT_backup/` into `./qbit-config/qBittorrent/BT_backup/`
before first launch. Optionally copy `~/.config/qBittorrent/qBittorrent.conf`
into `./qbit-config/qBittorrent/` to preserve categories and save paths.

Make sure the `Movies` and `TV` categories point at:
- `/home/lukaosojnik/jellyfin-media/movies`
- `/home/lukaosojnik/jellyfin-media/tv-series`

These paths must exist *inside* the qBittorrent container at the same absolute
location — that's handled by the `${JELLYFIN_MEDIA_BASE}` bind mount in
`docker-compose.yml`.

### 2. Get a NordVPN WireGuard private key

NordVPN doesn't expose WG keys in the dashboard. Use the gluetun helper:

```
docker run --rm -it --cap-add=NET_ADMIN \
  -e VPN_SERVICE_PROVIDER=nordvpn \
  -e OPENVPN_USER='<NordVPN service username>' \
  -e OPENVPN_PASSWORD='<NordVPN service password>' \
  qmcgaw/gluetun:latest format=env wireguard
```

Service credentials are at: https://my.nordaccount.com/dashboard/nordvpn/manual-configuration/

Copy the printed `WIREGUARD_PRIVATE_KEY=...` line into `.env`:

```
NORDVPN_WG_PRIVATE_KEY=<key>
NORDVPN_COUNTRIES=Switzerland     # optional override
TZ=Europe/Ljubljana               # optional override
```

### 3. Bring it up

```
docker compose up -d --build
```

### 4. Verify VPN egress and kill-switch

```
# Both must return the VPN IP, not your home IP:
docker exec gluetun wget -qO- https://ipinfo.io/ip
docker exec qbittorrent wget -qO- https://ipinfo.io/ip

# WebUI is reachable on host only:
curl -I http://127.0.0.1:8080

# Kill-switch: stop gluetun, qbit must lose internet:
docker stop gluetun
docker exec qbittorrent wget -qO- --timeout=5 https://ipinfo.io/ip  # should fail
docker start gluetun
```

### 5. WebUI first login

linuxserver/qbittorrent prints a temporary admin password in the container log
on first boot:

```
docker logs qbittorrent | grep -i password
```

Log in at http://127.0.0.1:8080, change the password under Tools → Options →
WebUI, and ensure categories `Movies` and `TV` exist with the save paths
above.

## Notes

- **No code changes required.** `QB_HOST=localhost` and `QB_PORT=8080` in
  `.env` still work because gluetun publishes 8080 on the host loopback.
- **No port forwarding on NordVPN.** Seed ratios will be poor. The bot already
  sets `seeding_time_limit=0` in `qbit.add_torrent`, so this is fine.
- **Rollback:** `docker compose stop gluetun qbittorrent`, relaunch desktop
  qBittorrent, no other changes needed.
