import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
    extensions: ['.js', '.jsx', '.ts', '.tsx'],
  },
  server: {
    proxy: {
      '/builder': {
        target: `http://localhost:${process.env.VITE_API_PORT || '8001'}`,
        changeOrigin: true,
      },
      '/token': {
        target: `http://localhost:${process.env.VITE_API_PORT || '8001'}`,
        changeOrigin: true,
      },
      '/admin': {
        target: `http://localhost:${process.env.VITE_API_PORT || '8001'}`,
        changeOrigin: true,
      },
      '/ws': {
        target: `http://localhost:${process.env.VITE_API_PORT || '8001'}`,
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
