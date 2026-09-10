import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    watch: {
      // Docker Desktop doesn't propagate native filesystem change events
      // for a bind-mounted Windows host path into the Linux container -
      // chokidar's default OS-event watcher then never fires and HMR goes
      // silent. docker-compose.yml sets CHOKIDAR_USEPOLLING for the app
      // service to fall back to polling there; unset natively, so `npm run
      // dev` outside Docker keeps the cheaper OS-event watcher.
      usePolling: process.env.CHOKIDAR_USEPOLLING === 'true',
    },
  },
})
