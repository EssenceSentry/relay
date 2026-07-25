FROM public.ecr.aws/lambda/python:3.12

COPY services/review_lambda/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY src/knowledge_core ${LAMBDA_TASK_ROOT}/knowledge_core
COPY services/review_lambda/handler.py ${LAMBDA_TASK_ROOT}/handler.py

CMD ["handler.lambda_handler"]
