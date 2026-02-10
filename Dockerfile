# Install python
FROM python:3.11-slim
# Install rasa pro
RUN pip install rasa-pro
# Set environment variables
# --- Accept build-time variables (from Render env) ---
ARG RASA_PRO_LICENSE
ARG OPENAI_API_KEY

ENV RASA_PRO_LICENSE=${RASA_PRO_LICENSE}
ENV OPENAI_API_KEY=${OPENAI_API_KEY}

# Get the code
WORKDIR /app
COPY . /app
USER root
EXPOSE 5005
RUN rasa train
# Run rasa server
#CMD exec rasa run --enable-api --cors "*" --port ${PORT} --endpoints endpoints.yml --model models
CMD ["bash", "-c", "rasa run --enable-api --cors '*' --port 5005 --endpoints endpoints.yml"]
