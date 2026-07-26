FROM public.ecr.aws/lambda/python:3.13

COPY services/notification_lambda/requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r requirements.txt

COPY src/knowledge_core ${LAMBDA_TASK_ROOT}/knowledge_core
COPY services/notification_lambda/handler.py ${LAMBDA_TASK_ROOT}/handler.py

CMD ["handler.lambda_handler"]
