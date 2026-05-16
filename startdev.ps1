$root = $PSScriptRoot

wt `
  new-tab --title "Frontend" cmd /k "cd /d `"$root\frontend`" && set NEXT_PUBLIC_API_URL=http://localhost:8080&& npm run dev" `
  ";" `
  new-tab --title "Backend" cmd /k "cd /d `"$root\backend`" && set FRONTEND_PUBLIC_URL=http://localhost:3000&& uvicorn app.main:app --reload --host 0.0.0.0 --port 8080"
