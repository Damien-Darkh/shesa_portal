# Shesa Portal

A local development and management portal built with Django, featuring integrations for Authentik, WireGuard, and Synology NAS.

## Prerequisites

* **WSL (Windows Subsystem for Linux)** (running native Linux filesystem, e.g., Ubuntu).
* **Docker & Docker Compose** installed and configured with appropriate user permissions.

---

## Project Structure & Setup

### 1. Environment Configuration (`.env`)
Ensure your `.env` file is configured in the project root with the appropriate local development overrides:

```env
DEBUG=true
USE_SSO=false
DB_NAME=shesa_portal
DB_USER=shesa
DB_PASSWORD=your_secure_password
WG_ENDPOINT=your_wireguard_endpoint
```

### 2. Docker Services (docker-compose.yml)
The project uses a containerized stack consisting of:

* **postgres:** Pinned to postgres:17-alpine to ensure proper compatibility with volume mounting standards.

* **web:** The Django application container built via the local Dockerfile.

## Local Development Workflow
* **Step 1: Start the Database:** Bring up the PostgreSQL container and verify it reaches a healthy state:

    ```Bash
    sudo docker compose up -d postgres
    ```

* **Step 2: Run Database Migrations:** Apply Django database migrations through the container environment:

    ```Bash
    sudo docker compose run --rm web python manage.py migrate
    ```
* **Step 3: Create a Superuser (Admin Account):** Because the project uses a custom user model/manager, use the Django shell snippet via Docker to provision your admin account (it@shesa.it):

    ```Bash
    sudo docker compose run --rm web python manage.py shell -c "
    from django.contrib.auth import get_user_model;
    User = get_user_model();
    if not User.objects.filter(email='it@shesa.it').exists():
        user = User.objects.create_user(email='it@shesa.it', password='your_secure_password')
        user.is_superuser = True
        user.is_staff = True
        user.save()
        print('Superuser created successfully!')
    else:
        print('Superuser already exists.')
    "
    ```
* **Step 4: Run the Full Application Stack:**

## Start all services in the background:

    ```Bash
    sudo docker compose up -d
    ```
Accessing the Portal
1. Once running, access the application locally in your browser:

2. Admin Panel: http://127.0.0.1:8000/admin/

3. Login: http://127.0.0.1:8000/login

4. Accounts: http://127.0.0.1:8000/accounts/

```html
<FollowUp label="Want to add a root URL redirect so visiting [http://127.0.0.1:8000/](http://127.0.0.1:8000/) goes straight to the admin panel?" query="How do I add a root URL redirect to /admin/ in config.urls?"/>
```