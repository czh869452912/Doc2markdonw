ARG MINERU_BASE_IMAGE=mineru:latest

FROM node:22-alpine AS pdfjs
WORKDIR /build
RUN npm pack pdfjs-dist@4.2.67 \
    && tar -xzf pdfjs-dist-4.2.67.tgz \
    && test -f package/build/pdf.worker.min.mjs \
    && test -d package/cmaps \
    && test -d package/standard_fonts

FROM ${MINERU_BASE_IMAGE}

COPY --from=pdfjs /build/package/build/pdf.worker.min.mjs /opt/mineru-ui-assets/pdf.worker.min.mjs
COPY --from=pdfjs /build/package/cmaps /opt/mineru-ui-assets/cmaps
COPY --from=pdfjs /build/package/standard_fonts /opt/mineru-ui-assets/standard_fonts
COPY patch_gradio_pdf.py /tmp/patch_gradio_pdf.py
COPY patch_output_paths.py /tmp/patch_output_paths.py

RUN python3 /tmp/patch_gradio_pdf.py \
    && python3 /tmp/patch_output_paths.py "$(python3 -c 'import importlib.util; print(importlib.util.find_spec("mineru.cli.output_paths").origin)')" \
    && rm /tmp/patch_gradio_pdf.py \
    && rm /tmp/patch_output_paths.py \
    && test -s /opt/mineru-ui-assets/pdf.worker.min.mjs

ENV GRADIO_ALLOWED_PATHS=/opt/mineru-ui-assets \
    GRADIO_ANALYTICS_ENABLED=False \
    GRADIO_SHARE=False \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    DO_NOT_TRACK=1

LABEL org.doc2markdown.component="mineru-gradio-offline" \
      org.doc2markdown.pdfjs.version="4.2.67" \
      org.doc2markdown.gradio-pdf.version="0.0.24"
