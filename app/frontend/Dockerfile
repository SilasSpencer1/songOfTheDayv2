FROM node:20-alpine as build
ARG VITE_API_BASE
ENV VITE_API_BASE=${VITE_API_BASE}
WORKDIR /app
COPY app/frontend/package.json ./
# Install deps; tolerate absence of lockfile
RUN npm i
COPY app/frontend ./
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
