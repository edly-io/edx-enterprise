# -*- coding: utf-8 -*-
"""
Generic learner data transmitter for integrated channels.
"""

import logging
from http import HTTPStatus

from django.apps import apps

from integrated_channels.exceptions import ClientError
from integrated_channels.integrated_channel.client import IntegratedChannelApiClient
from integrated_channels.integrated_channel.exporters.learner_data import LearnerExporterUtility
from integrated_channels.integrated_channel.transmitters import Transmitter
from integrated_channels.utils import generate_formatted_log, is_already_transmitted

LOGGER = logging.getLogger(__name__)


class LearnerTransmitter(Transmitter):
    """
    A generic learner data transmitter.

    It may be subclassed by specific integrated channel learner data transmitters for
    each integrated channel's particular learner data transmission requirements and expectations.
    """

    def __init__(self, enterprise_configuration, client=IntegratedChannelApiClient):
        """
        By default, use the abstract integrated channel API client which raises an error when used if not subclassed.
        """
        super().__init__(
            enterprise_configuration=enterprise_configuration,
            client=client
        )

    def _generate_common_params(self, **kwargs):
        """ Pulls labeled common params out of kwargs """
        app_label = kwargs.get('app_label', 'integrated_channel')
        enterprise_customer_uuid = self.enterprise_configuration.enterprise_customer.uuid or None
        lms_user_id = kwargs.get('learner_to_transmit', None)
        return app_label, enterprise_customer_uuid, lms_user_id

    def single_learner_assessment_grade_transmit(self, exporter, **kwargs):
        """
        Send an assessment level grade information to the integrated channel using the client.

        Args:
            exporter: The ``LearnerExporter`` instance used to send to the integrated channel.
            kwargs: Contains integrated channel-specific information for customized transmission variables.
                - app_label: The app label of the integrated channel for whom to store learner data records for.
                - model_name: The name of the specific learner data record model to use.
                - remote_user_id: The remote ID field name on the audit model that will map to the learner.
        """
        app_label, enterprise_customer_uuid, lms_user_id = self._generate_common_params(**kwargs)
        TransmissionAudit = apps.get_model(
            app_label=app_label,
            model_name=kwargs.get('model_name', 'LearnerDataTransmissionAudit'),
        )
        kwargs.update(
            TransmissionAudit=TransmissionAudit,
        )

        # Even though we're transmitting a learner, they can have records per assessment (multiple per course).
        for learner_data in exporter.single_assessment_level_export(**kwargs):
            LOGGER.info(generate_formatted_log(
                app_label, enterprise_customer_uuid, lms_user_id, learner_data.course_id,
                'create_assessment_reporting started for enrollment {enrollment_id}'.format(
                        enrollment_id=learner_data.enterprise_course_enrollment_id,
                        )))

            serialized_payload = learner_data.serialize(enterprise_configuration=self.enterprise_configuration)
            try:
                code, body = self.client.create_assessment_reporting(
                    getattr(learner_data, kwargs.get('remote_user_id')),
                    serialized_payload
                )
            except ClientError as client_error:
                code = client_error.status_code
                body = client_error.message
                self.handle_transmission_error(learner_data, client_error,
                                               app_label, enterprise_customer_uuid, lms_user_id, learner_data.course_id)

            except Exception:
                # Log additional data to help debug failures but just have Exception bubble
                self._log_exception_supplemental_data(
                    learner_data, 'create_assessment_reporting', app_label,
                    enterprise_customer_uuid, lms_user_id, learner_data.course_id)
                raise

            learner_data.status = str(code)
            learner_data.error_message = body if code >= 400 else ''

            learner_data.save()

    def assessment_level_transmit(self, exporter, **kwargs):
        """
        Send all assessment level grade information under an enterprise enrollment to the integrated channel using the
        client.

        Args:
            exporter: The learner assessment data exporter used to send to the integrated channel.
            kwargs: Contains integrated channel-specific information for customized transmission variables.
                - app_label: The app label of the integrated channel for whom to store learner data records for.
                - model_name: The name of the specific learner data record model to use.
                - remote_user_id: The remote ID field name of the learner on the audit model.
        """
        app_label, enterprise_customer_uuid, _ = self._generate_common_params(**kwargs)
        TransmissionAudit = apps.get_model(
            app_label=app_label,
            model_name=kwargs.get('model_name', 'LearnerDataTransmissionAudit'),
        )
        kwargs.update(
            TransmissionAudit=TransmissionAudit,
        )

        # Retrieve learner data for each existing enterprise enrollment under the enterprise customer
        # and transmit the data according to the current enterprise configuration.
        for learner_data in exporter.bulk_assessment_level_export():
            serialized_payload = learner_data.serialize(enterprise_configuration=self.enterprise_configuration)
            enterprise_enrollment_id = learner_data.enterprise_course_enrollment_id
            lms_user_id = LearnerExporterUtility.lms_user_id_for_ent_course_enrollment_id(
                enterprise_enrollment_id)

            # Check the last transmission for the current enrollment and see if the old grades match the new ones
            if is_already_transmitted(
                    TransmissionAudit,
                    enterprise_enrollment_id,
                    learner_data.grade,
                    learner_data.subsection_id
            ):
                # We've already sent a completion status for this enrollment
                LOGGER.info(generate_formatted_log(
                    app_label, enterprise_customer_uuid, lms_user_id, learner_data.course_id,
                    'Skipping previously sent EnterpriseCourseEnrollment {}'.format(enterprise_enrollment_id)
                ))
                continue

            try:
                code, body = self.client.create_assessment_reporting(
                    getattr(learner_data, kwargs.get('remote_user_id')),
                    serialized_payload
                )
                LOGGER.info(generate_formatted_log(
                    app_label, enterprise_customer_uuid, lms_user_id, learner_data.course_id,
                    'create_assessment_reporting successfully completed for EnterpriseCourseEnrollment {}'.format(
                        enterprise_enrollment_id,
                    )
                ))
            except ClientError as client_error:
                code = client_error.status_code
                body = client_error.message
                self.handle_transmission_error(learner_data, client_error, app_label,
                                               enterprise_customer_uuid, lms_user_id, learner_data.course_id)

            except Exception:
                # Log additional data to help debug failures but just have Exception bubble
                self._log_exception_supplemental_data(
                    learner_data, 'create_assessment_reporting', app_label,
                    enterprise_customer_uuid, lms_user_id, learner_data.course_id)
                raise

            learner_data.status = str(code)
            learner_data.error_message = body if code >= 400 else ''

            learner_data.save()

    def transmit(self, payload, **kwargs):
        """
        Send a completion status call to the integrated channel using the client.

        Args:
            payload: The learner data exporter.
            kwargs: Contains integrated channel-specific information for customized transmission variables.
                - app_label: The app label of the integrated channel for whom to store learner data records for.
                - model_name: The name of the specific learner data record model to use.
                - remote_user_id: The remote ID field name of the learner on the audit model.
        """
        app_label, enterprise_customer_uuid, _ = self._generate_common_params(**kwargs)
        TransmissionAudit = apps.get_model(
            app_label=app_label,
            model_name=kwargs.get('model_name', 'LearnerDataTransmissionAudit'),
        )
        kwargs.update(
            TransmissionAudit=TransmissionAudit,
        )
        # Since we have started sending courses to integrated channels instead of course runs,
        # we need to attempt to send transmissions with course keys and course run ids in order to
        # ensure that we account for whether courses or course runs exist in the integrated channel.
        # The exporters have been changed to return multiple transmission records to attempt,
        # one by course key and one by course run id.
        # If the transmission with the course key succeeds, the next one will get skipped.
        # If it fails, the one with the course run id will be attempted and (presumably) succeed.
        for learner_data in payload.export(**kwargs):
            serialized_payload = learner_data.serialize(enterprise_configuration=self.enterprise_configuration)

            enterprise_enrollment_id = learner_data.enterprise_course_enrollment_id
            lms_user_id = LearnerExporterUtility.lms_user_id_for_ent_course_enrollment_id(
                enterprise_enrollment_id)

            if not learner_data.course_completed:
                # The user has not completed the course, so we shouldn't send a completion status call
                LOGGER.info(generate_formatted_log(
                    app_label, enterprise_customer_uuid, lms_user_id, learner_data.course_id,
                    f'Skipping in-progress enterprise enrollment:: id: {enterprise_enrollment_id}'
                    f', course_id: {learner_data.course_id}'
                ))
                continue

            grade = getattr(learner_data, 'grade', None)
            if is_already_transmitted(TransmissionAudit, enterprise_enrollment_id, grade):
                # We've already sent a completion status for this enrollment
                LOGGER.info(generate_formatted_log(
                    app_label, enterprise_customer_uuid, lms_user_id, learner_data.course_id,
                    'Skipping previously sent enterprise enrollment {}'.format(enterprise_enrollment_id)))
                continue

            try:
                code, body = self.client.create_course_completion(
                    getattr(learner_data, kwargs.get('remote_user_id')),
                    serialized_payload
                )
                if code >= HTTPStatus.BAD_REQUEST.value:
                    raise ClientError(f'Client create_course_completion failed: {body}', code)

                LOGGER.info(generate_formatted_log(
                    app_label, enterprise_customer_uuid, lms_user_id, learner_data.course_id,
                    'Successfully sent completion status call for enterprise enrollment {}'.format(
                        enterprise_enrollment_id,
                    )
                ))
            except ClientError as client_error:
                code = client_error.status_code
                body = client_error.message
                self.handle_transmission_error(learner_data, client_error, app_label,
                                               enterprise_customer_uuid, lms_user_id, learner_data.course_id)

            except Exception:
                # Log additional data to help debug failures but have Exception bubble
                self._log_exception_supplemental_data(
                    learner_data, 'create_assessment_reporting', app_label,
                    enterprise_customer_uuid, lms_user_id, learner_data.course_id)
                raise

            learner_data.status = str(code)
            learner_data.error_message = body if code >= 400 else ''

            learner_data.save()

    def deduplicate_assignment_records_transmit(self, exporter, **kwargs):
        """
        Remove duplicated assessments sent to the integrated channel using the client.

        Args:
            exporter: The learner completion data payload to send to the integrated channel.
            kwargs: Contains integrated channel-specific information for customized transmission variables.
                - app_label: The app label of the integrated channel for whom to store learner data records for.
                - model_name: The name of the specific learner data record model to use.
                - remote_user_id: The remote ID field name of the learner on the audit model.
        """
        app_label, enterprise_customer_uuid, _ = self._generate_common_params(**kwargs)
        courses = exporter.export_unique_courses()
        code, body = self.client.cleanup_duplicate_assignment_records(courses)

        if code >= 400:
            LOGGER.exception(generate_formatted_log(
                app_label,
                enterprise_customer_uuid,
                None,
                None,
                'Deduping assignments transmission experienced a failure, received the error message: {}'.format(body)
            ))
        else:
            LOGGER.info(generate_formatted_log(
                app_label,
                enterprise_customer_uuid,
                None,
                None,
                'Deduping assignments transmission finished successfully, received message: {}'.format(body)
            ))

    def _log_exception_supplemental_data(self, learner_data, operation_name,
                                         integrated_channel_name, enterprise_customer_uuid, learner_id, course_id):
        """ Logs extra payload and parameter data to help debug which learner data caused an exception. """
        LOGGER.exception(generate_formatted_log(
            integrated_channel_name, enterprise_customer_uuid, learner_id, course_id,
            '{operation_name} failed with Exception for '
            'enterprise enrollment {enrollment_id} with payload {payload}'.format(
                operation_name=operation_name,
                enrollment_id=learner_data.enterprise_course_enrollment_id,
                payload=learner_data
            )), exc_info=True)

    def handle_transmission_error(self, learner_data, client_exception,
                                  integrated_channel_name, enterprise_customer_uuid, learner_id, course_id):
        """Handle the case where the transmission fails."""
        LOGGER.exception(generate_formatted_log(
            integrated_channel_name, enterprise_customer_uuid, learner_id, course_id,
            'Failed to send completion status call for enterprise enrollment {}'
            'with payload {}'
            '\nError message: {}'
            '\nError status code: {}'.format(
                learner_data.enterprise_course_enrollment_id,
                learner_data,
                client_exception.message,
                client_exception.status_code
            )))
