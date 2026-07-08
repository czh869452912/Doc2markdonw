# Doc2markdown Air-Gap Deployment

This repository prepares an offline deployment bundle for an intranet document
conversion service based on RAGFlow, MinerU, and a lightweight Markdown
conversion service.

The intended flow is:

1. Run the Windows packaging script on a machine that can access Docker
   registries and GitHub.
2. Copy the generated bundle to the Linux intranet server.
3. Run the Linux deployment script to load images and start the stack behind a
   single configurable gateway port.

Start with [deploy/ragflow-mineru/README.md](deploy/ragflow-mineru/README.md).
