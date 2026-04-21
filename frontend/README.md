# Frontend Test App

Small React frontend for exercising the FastAPI backend without relying on Swagger UI.

## Run

1. Start the API on `http://localhost:8000`.
2. Install frontend dependencies:

```bash
npm install
```

3. Start the frontend:

```bash
npm run dev
```

Open `http://localhost:5173`.

## Notes

- By default, the frontend calls the backend through the Vite proxy at `/api`.
- To point at another backend URL, create a `.env` file inside `frontend/` with:

```bash
VITE_API_BASE_URL=http://localhost:8000
```

- Sessions are stored in backend memory, so restarting the API invalidates previous session IDs.
- The backend accepts `.pdf`, `.xlsx`, and common image formats.
