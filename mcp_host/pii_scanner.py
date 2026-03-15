"""
PII Scanning and Redaction Service

This module provides a centralized service for detecting and redacting
Personally Identifiable Information (PII) from text using the
Microsoft Presidio toolkit.
"""

import logging
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

logger = logging.getLogger(__name__)

class PiiScanner:
    """A service to detect and redact PII in text."""

    def __init__(self):
        try:
            # Initialize the analyzer with the downloaded spaCy model
            self.analyzer = AnalyzerEngine()
            self.anonymizer = AnonymizerEngine()
            logger.info("✓ PII Scanner initialized successfully.")
        except Exception as e:
            logger.error(f"✗ Failed to initialize PII Scanner: {e}", exc_info=True)
            # Set to None to gracefully degrade
            self.analyzer = None
            self.anonymizer = None

    def scan_and_redact(self, text: str, trace_id: str = None) -> str:
        """
        Analyzes text for PII and returns a redacted version.

        If the scanner is not initialized, it returns the original text.
        """
        if not self.analyzer or not self.anonymizer:
            logger.warning(f"[{trace_id}] PII scanner not available. Skipping redaction.")
            return text

        try:
            # Analyze the text to find PII entities
            analyzer_results = self.analyzer.analyze(
                text=text,
                language='en'
            )

            if not analyzer_results:
                # No PII found, return original text
                return text

            # Anonymize the detected entities
            anonymized_result = self.anonymizer.anonymize(
                text=text,
                analyzer_results=analyzer_results,
                operators={
                    "DEFAULT": OperatorConfig(
                        "replace",
                        {"new_value": "<REDACTED>"}
                    ),
                    "PHONE_NUMBER": OperatorConfig(
                        "replace",
                        {"new_value": "<PHONE>"}
                    ),
                    "EMAIL_ADDRESS": OperatorConfig(
                        "replace",
                        {"new_value": "<EMAIL>"}
                    ),
                    "PERSON": OperatorConfig(
                        "replace",
                        {"new_value": "<PERSON>"}
                    )
                }
            )
            
            if anonymized_result and anonymized_result.text:
                logger.info(f"[{trace_id}] Redacted PII from text. Found {len(analyzer_results)} entities.")
                return anonymized_result.text
            
            return text

        except Exception as e:
            logger.error(f"[{trace_id}] Error during PII redaction: {e}", exc_info=True)
            # Return original text in case of an error during the process
            return text

# Singleton instance
pii_scanner = PiiScanner()
