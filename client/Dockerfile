ARG BUILD_MODE="production"

# Build stage for client
FROM node:latest AS builder

WORKDIR /app

# Copy package files first for better caching
COPY package*.json ./
RUN npm install

# Copy the rest of the code
COPY . .

# Redeclare ARG in this stage
ARG BUILD_MODE
RUN npm run build -- --mode ${BUILD_MODE}

# Nginx stage
FROM nginx:alpine

# Copy nginx configuration as a template. The nginx:alpine entrypoint runs
# envsubst over /etc/nginx/templates/*.template at container start, writing the
# result to /etc/nginx/conf.d/. Only variables present in the environment are
# substituted, so nginx runtime variables ($host, $uri, ...) are preserved.
COPY default.conf.template /etc/nginx/templates/default.conf.template

# Default vhost names; override at runtime (e.g. in docker-compose.prod.yaml)
# with your real public hostnames. "_" is nginx's catch-all default server.
ENV NGINX_SERVER_NAME=_ \
    NGINX_FLOWER_SERVER_NAME=flower.localhost

# Copy the client build files from build stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy the PDF.js worker file directly to the root of the web server
COPY --from=builder /app/node_modules/pdfjs-dist/build/pdf.worker.min.mjs /usr/share/nginx/html/pdf.worker.min.js


EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]