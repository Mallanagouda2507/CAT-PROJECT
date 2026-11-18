from google.api_core.exceptions import GoogleAPICallError, InvalidArgument, NotFound
from google.api_core.client_options import ClientOptions
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import documentai


class DocumentAIConfigurationError(RuntimeError):
    pass


class DocumentAIProcessingError(RuntimeError):
    pass


def is_configured(config):
    return all(
        (
            config.get("GOOGLE_CLOUD_PROJECT"),
            config.get("GOOGLE_CLOUD_LOCATION"),
            config.get("GOOGLE_CLOUD_PROCESSOR_ID"),
        )
    )


def process_invoice(config, content, mime_type):
    if not is_configured(config):
        raise DocumentAIConfigurationError(
            "Google Cloud Document AI is not configured. Set the project, location, "
            "processor ID, and application credentials."
        )

    try:
        client = documentai.DocumentProcessorServiceClient(
            client_options=ClientOptions(
                api_endpoint=f"{config.get('GOOGLE_CLOUD_LOCATION')}-documentai.googleapis.com"
            )
        )
    except DefaultCredentialsError as error:
        raise DocumentAIConfigurationError(
            "Google application credentials are unavailable. Configure "
            "GOOGLE_APPLICATION_CREDENTIALS or Application Default Credentials."
        ) from error
    processor_name = client.processor_path(
        config.get("GOOGLE_CLOUD_PROJECT"),
        config.get("GOOGLE_CLOUD_LOCATION"),
        config.get("GOOGLE_CLOUD_PROCESSOR_ID"),
    )
    raw_document = documentai.RawDocument(content=content, mime_type=mime_type)
    request = documentai.ProcessRequest(name=processor_name, raw_document=raw_document)

    try:
        response = client.process_document(request=request)
    except NotFound as error:
        raise DocumentAIProcessingError(
            "The configured processor was not found. Check the project, location, and processor ID."
        ) from error
    except InvalidArgument as error:
        raise DocumentAIProcessingError(
            "Google Cloud Document AI rejected the document or processor configuration."
        ) from error
    except GoogleAPICallError as error:
        raise DocumentAIProcessingError(
            "Google Cloud Document AI could not process this document. Check API access and billing."
        ) from error
    finally:
        client.transport.close()
    return response.document
