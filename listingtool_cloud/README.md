# ListingTool Cloud User Center

Public cloud backend for ListingTool desktop clients.

Endpoints:
- GET /api/v1/health
- GET /api/v1/status
- POST /api/v1/bootstrap
- POST /api/v1/login
- GET /api/v1/me
- GET /api/v1/users
- POST /api/v1/users
- POST /api/v1/users/<id>/toggle
- DELETE /api/v1/users/<id>
- GET /api/v1/version

Render start command:
`gunicorn listingtool_cloud.server:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`
