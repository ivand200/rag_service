FROM node:22-alpine AS build

WORKDIR /app

COPY frontend/package.json frontend/tsconfig.json frontend/vite.config.ts frontend/index.html ./
COPY frontend/src ./src

RUN npm install

ARG VITE_API_BASE_URL=/api
ARG VITE_CLERK_PUBLISHABLE_KEY
ARG VITE_APP_ENV=production
ARG VITE_AUTH_MODE=clerk
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_CLERK_PUBLISHABLE_KEY=${VITE_CLERK_PUBLISHABLE_KEY}
ENV VITE_APP_ENV=${VITE_APP_ENV}
ENV VITE_AUTH_MODE=${VITE_AUTH_MODE}

RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
