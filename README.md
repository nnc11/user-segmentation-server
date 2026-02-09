# User Segmentation Server

This project is an HTTP server built with Python/Flask that evaluates user segment rules based on ANSI SQL conditions.

## Features
- **Custom SQL Parser:** Implemented using a recursive descent parser.
- **Secure Evaluation:** Avoids `eval()` for arithmetic operations to prevent code injection.
- **Dockerized:** Ready to deploy using Docker.

## How to Run
1. Build the image:
   `docker build -t segmentation-server .`
2. Run the container:
   `docker run -e PORT=3000 -p 3000:3000 segmentation-server`
   
## AI Usage & Attribution
**GitHub Copilot** was used as an AI collaborator during the development of this project. 
