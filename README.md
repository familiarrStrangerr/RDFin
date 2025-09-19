````markdown
# RDfin

![RDfin Logo](app/static/logo.png)

**RDfin** is a lightweight self-hosted web service that integrates [Real-Debrid](https://real-debrid.com/) with [Jellyfin](https://jellyfin.org/).  
It generates `.strm` files from Real-Debrid links so you can stream cached content directly in Jellyfin, without downloading large files locally.

---

## ✨ Features

- 📺 Supports **movies** and **TV episodes**  
- 🗂 Automatically organizes `.strm` files into proper folders for Jellyfin  
- 📝 Maintains **daily log files** of all cached links (separate for movies and TV)  
- 🔄 One-click **refresh** of cached links when RD links expire  
- 🗑 Delete old logs directly from the web UI  
- 🌙 **Dark mode** toggle in the web GUI  
- 🐳 Optimized for Docker — simple to deploy with volume mounts for media and logs  

---

## 🚀 Getting Started

### 1. Clone this repository
```bash
git clone https://github.com/<yourusername>/rdfin.git
cd rdfin
````

### 2. Configure environment variables

Create a `.env` file in the project root:

```env
FLASK_SECRET=your_random_secret_here
REALDEBRID_TOKEN=your_realdebrid_api_token
```

Generate a strong secret key (64 hex chars recommended):

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

### 3. Docker Compose

Example `docker-compose.yml`:

```yaml
version: "3.8"
services:
  rdfin-web:
    image: docker.io/<yourusername>/rdfin-web:latest
    container_name: rdfin_web
    env_file:
      - .env
    volumes:
      - /path/to/jellyfin/media/Movies:/media/movies:rw
      - /path/to/jellyfin/media/TV_Shows:/media/tv:rw
      - ./rd-strm_data:/fetch_logs:rw
    ports:
      - "3001:3001"
    restart: unless-stopped
```

Start the service:

```bash
docker compose up -d
```

Open in browser:

```
http://localhost:3001
```

---

## 📂 Directory Layout

* `/media/movies` → `.strm` files for movies
* `/media/tv` → `.strm` files for TV episodes
* `/fetch_logs/movies` → daily log files of added movie links
* `/fetch_logs/tv` → daily log files of added TV episode links

---

## 🖥 Web GUI

* **Add Movies**: paste multiple links (one per line)
* **Add Episodes**: specify show + season, then paste episode links
* **Recently fetched** section shows newly added `.strm` files
* **Log dropdowns** allow refreshing or deleting logs per day
* **Dark mode toggle** in header
* Favicon + logo branding included

*(Insert screenshots here)*

---

## 🔒 Security Notes

* Your `.env` file (with RD token) is **not copied into the image**.
* Keep `.env` safe and out of version control (`.gitignore`).
* Rotate your Real-Debrid API token if it leaks.

---

## 🛠 Development

Build the image locally:

```bash
docker build -t rdfin-web:latest .
```

Run in development mode:

```bash
docker run -it --rm -p 3001:3001 \
  -v $(pwd)/app:/app \
  --env-file .env rdfin-web:latest
```

---

## 📦 Roadmap

* [ ] Multi-user support
* [ ] Configurable naming templates for `.strm` files
* [ ] Improved error reporting for failed links
* [ ] Optional direct playback testing from web UI

---

## 📜 License

MIT License.
RDfin is not affiliated with Real-Debrid or Jellyfin.

---

## 🙌 Acknowledgements

* [Real-Debrid API](https://api.real-debrid.com/)
* [Jellyfin](https://jellyfin.org/)
* [Flask](https://flask.palletsprojects.com/)
* [Docker](https://www.docker.com/)

```
