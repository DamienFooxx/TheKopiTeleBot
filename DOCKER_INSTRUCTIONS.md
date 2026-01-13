# Docker Instructions for TheKopiTeleBot

I have prepared the project for Dockerization by creating a `Dockerfile` and a `.dockerignore` file. However, it seems you are facing network issues that prevent you from building the Docker image. This is a common issue and is related to your local network configuration.

## Troubleshooting the `TLS handshake timeout` error

The error `net/http: TLS handshake timeout` indicates that Docker is unable to connect to the Docker Hub to download the base image. This is very likely due to a proxy, firewall, or DNS issue on your network.

Here are some steps you can take to resolve this issue:

### 1. Are you behind a corporate proxy?

If you are on a corporate network, you are most likely behind a proxy. You need to configure Docker Desktop to use this proxy.

*   Go to **Docker Desktop Settings > Resources > Proxies**.
*   Enable "Manual proxy configuration".
*   Enter your HTTP and HTTPS proxy details. You can get these from your IT department.
*   Apply the changes and restart Docker.

If you have configured the proxy in Docker Desktop and it's still not working, you might need to pass the proxy settings to the build command itself.

```bash
docker build \
  --build-arg HTTP_PROXY="http://your_proxy_host:port" \
  --build-arg HTTPS_PROXY="http://your_proxy_host:port" \
  -t kopi-tele-bot .
```

### 2. DNS Configuration

Sometimes, the default DNS server used by Docker can cause issues. You can try setting it to a public DNS server like Google's (`8.8.8.8`).

*   Go to **Docker Desktop Settings > Docker Engine**.
*   In the JSON configuration file, add the following:

```json
{
  "dns": ["8.8.8.8", "8.8.4.4"]
}
```

*   Apply the changes and restart Docker.

### 3. Firewall and Antivirus

Your firewall or antivirus software might be blocking the connection. Try temporarily disabling them to see if that resolves the issue. If it does, you will need to add an exception for Docker.

### 4. Restart Docker

Sometimes, a simple restart of Docker Desktop can resolve a lot of issues.

## Alternative: Running without Docker

If you are still unable to resolve the Docker issue, you can run the bot directly on your machine. You already have a Python environment set up.

1.  Make sure you have all the dependencies installed:
    ```bash
    pip install -r requirements.txt
    ```
2.  Set the environment variables `TELEGRAM_BOT_TOKEN` and `ADMIN_CHAT_ID`.
3.  Run the bot:
    ```bash
    python main.py
    ```

## Building and Running with Docker (once network is resolved)

Once you have resolved the network issue, you can proceed with building and running the Docker container.

### 1. Build the Docker Image

```bash
docker build -t kopi-tele-bot .
```

### 2. Run the Docker Container

```bash
docker run -d --name kopi-bot -v "%cd%/data:/app/data" -e TELEGRAM_BOT_TOKEN="8450024089:AAG0hAHpwjgjoXnsZmVQ21S290vYGDnZ4QQ" -e ADMIN_CHAT_ID="226739855" kopi-tele-bot
```
