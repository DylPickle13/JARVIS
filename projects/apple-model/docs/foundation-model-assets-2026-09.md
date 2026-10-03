# Apple Foundation Model asset inventory (local snapshot)

Snapshot: macOS 27.0 (Build 26A428), 2026-09-16. Source: `AutoAssetLocker` state files matching `com.apple.MobileAsset.UAF.FM.GenerativeModels`; every row reported `entryStatus=LOADED`.

These are private asset specifiers, not a supported public model list. “LOADED” means the asset manager has the package locked/available; it does not mean every model is resident in DRAM or used by `apple-model`. Descriptions are direct where the identifier is self-describing and otherwise explicitly marked as inferred/opaque. Trailing version numbers are Apple asset versions.

**Important:** `.draft` entries are companion assets for the same task, generally used for speculative decoding; they are not separate user-selectable models. The `gm.server` rows are server/PCC feature adapters, not local cloud model weights.

## Catalog metadata

| # | Asset specifier | Version | What it is for |
|---:|---|---|---|
| 1 | `com.apple.fm.generativemodels.uaf.metadata` | `4.46.3.13.204965` | UAF generative-model catalog metadata/manifest; not an inference model. |
## On-device ~300M utility/guard tier

| # | Asset specifier | Version | What it is for |
|---:|---|---|---|
| 2 | `com.apple.fm.language.instruct_300m.action_validator.generic` | `14.4.0.13.103108` | Validates generated actions or structured action payloads before an Apple feature executes them. |
| 3 | `com.apple.fm.language.instruct_300m.base.generic` | `14.3.81624.13.204821` | Shared base weights for the small ~300M instruction-model tier. |
| 4 | `com.apple.fm.language.instruct_300m.factual_consistency_classifier.generic` | `14.1.0.13.103108` | Classifies whether an answer is consistent with the supplied source/input. |
| 5 | `com.apple.fm.language.instruct_300m.gvicc.generic` | `14.2.0.13.103108` | Opaque internal classifier. Apple does not publish what “gvicc” expands to or its exact labels. |
| 6 | `com.apple.fm.language.instruct_300m.image_tokenizer.generic` | `14.3.81619.13.204821` | Converts image input into model-compatible tokens/features for 300M multimodal tasks. |
| 7 | `com.apple.fm.language.instruct_300m.ipi_classifier.generic` | `14.4.0.13.103108` | Opaque internal classifier. The identifier alone does not establish its target labels or user-facing feature. |
| 8 | `com.apple.fm.language.instruct_300m.misc_safety.generic` | `14.1.0.13.103108` | Miscellaneous safety/content classification or filtering. |
| 9 | `com.apple.fm.language.instruct_300m.mm_guard.generic` | `14.2.0.13.103108` | Multimodal guard: screens image/text inputs or outputs for policy/safety conditions. |
| 10 | `com.apple.fm.language.instruct_300m.open_ended_extract.draft.generic` | `14.7.81624.13.204837` | Extracts fields, entities, or other structured information from free-form text. Draft companion used for low-latency speculative decoding. |
| 11 | `com.apple.fm.language.instruct_300m.open_ended_extract.generic` | `14.7.0.13.103108` | Extracts fields, entities, or other structured information from free-form text. |
| 12 | `com.apple.fm.language.instruct_300m.prepubescent_safety.generic` | `14.1.0.13.103108` | Specialized child-safety classifier/guard. |
| 13 | `com.apple.fm.language.instruct_300m.safety.generic` | `14.3.0.13.103108` | General safety classifier/guard for the small instruction tier. |
| 14 | `com.apple.fm.language.instruct_300m.structural_integrity.generic` | `14.1.0.13.103108` | Checks structural validity/integrity of generated structured output. |
| 15 | `com.apple.fm.language.instruct_300m.tokenizer.generic` | `14.3.0.13.204674` | Text tokenizer for the ~300M tier. |
| 16 | `com.apple.fm.language.instruct_300m.voice_control_ai_v2.generic` | `14.1.0.13.103108` | Interprets voice-assistant control requests; exact internal label set is private. |
| 17 | `com.apple.fm.language.instruct_300m.voice_control_ai_v2.image_tokenizer_adapter.generic` | `14.1.0.13.103108` | Image-token adapter used with the voice-control-AI v2 path; exact product behavior is private. |
## On-device 3B tier (mostly sparse/Core Advanced assets)

| # | Asset specifier | Version | What it is for |
|---:|---|---|---|
| 18 | `com.apple.fm.language.instruct_3b.adm_prompt_analyzer.draft.generic_sparse` | `16.0.81624.13.204836` | Analyzes/normalizes prompts intended for Apple’s ADM image generation/editing pipeline (sparse/Core Advanced variant). Draft companion used for low-latency speculative decoding. |
| 19 | `com.apple.fm.language.instruct_3b.adm_prompt_analyzer.generic_sparse` | `16.0.0.13.103114` | Analyzes/normalizes prompts intended for Apple’s ADM image generation/editing pipeline (sparse/Core Advanced variant). |
| 20 | `com.apple.fm.language.instruct_3b.asr_natural_dictation_speech.generic_sparse` | `16.1.0.13.103123` | Automatic-speech-recognition/dictation processing, such as natural-dictation correction (sparse variant). |
| 21 | `com.apple.fm.language.instruct_3b.auto_tagger.generic` | `12.0.0.13.101733` | Automatically assigns semantic tags/categories to content; exact consumer is not published. |
| 22 | `com.apple.fm.language.instruct_3b.base.generic_sparse` | `16.0.81624.13.204851` | Shared sparse 3B-active base for AFM 3 Core Advanced and its task adapters. |
| 23 | `com.apple.fm.language.instruct_3b.embedding_preprocessor.generic_sparse` | `16.0.0.13.103114` | Prepares/normalizes text before the embeddings path. |
| 24 | `com.apple.fm.language.instruct_3b.embeddings.generic` | `14.0.81624.13.204857` | Produces text embeddings for similarity, retrieval, or classification; not exposed by the public CLI. |
| 25 | `com.apple.fm.language.instruct_3b.fm_api_content_tagger.adapter_metadata_override.generic_sparse` | `16.0.0.13.204764` | Catalog metadata/override that binds the public FoundationModels content-tagging use case to its adapter. |
| 26 | `com.apple.fm.language.instruct_3b.fm_api_generic.draft.generic_sparse` | `16.0.81624.13.204770` | Generic public-API adapter/binding, used by the content-tagging path rather than the default 3B-budget binding. Draft companion used for low-latency speculative decoding. |
| 27 | `com.apple.fm.language.instruct_3b.fm_api_generic.generic_sparse` | `16.0.0.13.103131` | Generic public-API adapter/binding, used by the content-tagging path rather than the default 3B-budget binding. |
| 28 | `com.apple.fm.language.instruct_3b.fm_api_generic_1b.generic_sparse` | `16.0.0.13.103113` | Public-API sparse compute-budget binding targeting roughly 1B active parameters. |
| 29 | `com.apple.fm.language.instruct_3b.fm_api_generic_2b.generic_sparse` | `16.0.0.13.103113` | Public-API sparse compute-budget binding targeting roughly 2B active parameters. |
| 30 | `com.apple.fm.language.instruct_3b.fm_api_generic_3b.generic_sparse` | `16.1.0.13.103120` | Public-API sparse compute-budget binding targeting roughly 3B active parameters; the default general path uses this family. |
| 31 | `com.apple.fm.language.instruct_3b.holdassistwaittime.adapter_metadata_override.generic_sparse` | `16.0.0.13.204693` | Catalog metadata/override for Hold Assist wait-time handling/estimation. |
| 32 | `com.apple.fm.language.instruct_3b.homekit_summary_notifications.adapter_metadata_override.generic_sparse` | `16.1.0.13.204709` | Catalog metadata/override for summarizing HomeKit notifications. |
| 33 | `com.apple.fm.language.instruct_3b.image_encoder.generic_sparse` | `16.0.81624.13.204839` | Encodes images into representations consumed by the multimodal language model. |
| 34 | `com.apple.fm.language.instruct_3b.image_playground_edit_suggestions.draft.generic_sparse` | `16.2.81624.13.204742` | Generates suggestions for Image Playground image-editing prompts/actions. Draft companion used for low-latency speculative decoding. |
| 35 | `com.apple.fm.language.instruct_3b.image_playground_edit_suggestions.generic_sparse` | `16.2.0.13.103129` | Generates suggestions for Image Playground image-editing prompts/actions. |
| 36 | `com.apple.fm.language.instruct_3b.lw_planner_v1.draft.generic_sparse` | `16.0.81624.13.204839` | Lightweight planner for assistant/action workflows; likely an internal Siri/Apple Intelligence path. Draft companion used for low-latency speculative decoding. |
| 37 | `com.apple.fm.language.instruct_3b.lw_planner_v1.generic_sparse` | `16.0.0.13.103114` | Lightweight planner for assistant/action workflows; likely an internal Siri/Apple Intelligence path. |
| 38 | `com.apple.fm.language.instruct_3b.machine_translation.draft.generic_sparse` | `16.2.81624.13.204971` | Generates machine translations. Draft companion used for low-latency speculative decoding. |
| 39 | `com.apple.fm.language.instruct_3b.machine_translation.generic_sparse` | `16.2.0.13.103160` | Generates machine translations. |
| 40 | `com.apple.fm.language.instruct_3b.mail_reply.draft.generic_sparse` | `16.0.81624.13.204820` | Generates short Mail reply text. Draft companion used for low-latency speculative decoding. |
| 41 | `com.apple.fm.language.instruct_3b.mail_reply.generic_sparse` | `16.0.0.13.103114` | Generates short Mail reply text. |
| 42 | `com.apple.fm.language.instruct_3b.messages_action.draft.generic_sparse` | `16.0.81624.13.204820` | Understands or generates actions for Messages workflows. Draft companion used for low-latency speculative decoding. |
| 43 | `com.apple.fm.language.instruct_3b.messages_action.generic_sparse` | `16.0.0.13.103114` | Understands or generates actions for Messages workflows. |
| 44 | `com.apple.fm.language.instruct_3b.news_topic_summarization.draft.generic_sparse` | `16.0.81624.13.204811` | Summarizes news by topic. Draft companion used for low-latency speculative decoding. |
| 45 | `com.apple.fm.language.instruct_3b.news_topic_summarization.generic_sparse` | `16.0.0.13.103113` | Summarizes news by topic. |
| 46 | `com.apple.fm.language.instruct_3b.open_ended_extract.draft.generic_sparse` | `16.1.81624.13.204811` | Extracts fields, entities, or other structured information from free-form text. Draft companion used for low-latency speculative decoding. |
| 47 | `com.apple.fm.language.instruct_3b.open_ended_extract.generic_sparse` | `16.1.0.13.103126` | Extracts fields, entities, or other structured information from free-form text. |
| 48 | `com.apple.fm.language.instruct_3b.personalized_smart_reply.draft.generic_sparse` | `16.0.81624.13.204811` | Generates personalized suggested replies. Draft companion used for low-latency speculative decoding. |
| 49 | `com.apple.fm.language.instruct_3b.personalized_smart_reply.generic_sparse` | `16.0.0.13.103114` | Generates personalized suggested replies. |
| 50 | `com.apple.fm.language.instruct_3b.photos_library_understanding_mm.generic_sparse` | `16.0.0.13.103114` | Multimodal understanding/indexing of Photos-library content. |
| 51 | `com.apple.fm.language.instruct_3b.photos_memories_asset_curation_outlier.draft.generic_sparse` | `16.0.81624.13.204808` | Detects outlier/unusual assets during Photos Memories curation. Draft companion used for low-latency speculative decoding. |
| 52 | `com.apple.fm.language.instruct_3b.photos_memories_asset_curation_outlier.generic_sparse` | `16.0.0.13.103113` | Detects outlier/unusual assets during Photos Memories curation. |
| 53 | `com.apple.fm.language.instruct_3b.photos_memories_title.adapter_metadata_override.generic_sparse` | `16.0.0.13.204692` | Catalog metadata/override for Photos Memories title generation. |
| 54 | `com.apple.fm.language.instruct_3b.proofreading_review.draft.generic_sparse` | `16.1.81624.13.204807` | Finds proofreading/review issues and suggests writing corrections. Draft companion used for low-latency speculative decoding. |
| 55 | `com.apple.fm.language.instruct_3b.proofreading_review.generic_sparse` | `16.1.0.13.103113` | Finds proofreading/review issues and suggests writing corrections. |
| 56 | `com.apple.fm.language.instruct_3b.reminders_suggest_action_items.draft.generic_sparse` | `16.0.81624.13.204809` | Finds or suggests action items for Reminders. Draft companion used for low-latency speculative decoding. |
| 57 | `com.apple.fm.language.instruct_3b.reminders_suggest_action_items.generic_sparse` | `16.0.0.13.103112` | Finds or suggests action items for Reminders. |
| 58 | `com.apple.fm.language.instruct_3b.safari_magic_extensions_app_store_search_terms.adapter_metadata_override.generic_sparse` | `16.0.0.13.204693` | Catalog metadata/override for generating App Store search terms for Safari Magic Extensions. |
| 59 | `com.apple.fm.language.instruct_3b.safari_notify_me_when_suggestions.adapter_metadata_override.generic_sparse` | `16.0.0.13.204693` | Catalog metadata/override for Safari “Notify Me” suggestions. |
| 60 | `com.apple.fm.language.instruct_3b.safari_tab_group_topic.adapter_metadata_override.generic_sparse` | `16.1.0.13.204748` | Catalog metadata/override for inferring Safari tab-group topics. |
| 61 | `com.apple.fm.language.instruct_3b.shortcuts_ask_afm_action_3b.adapter_metadata_override.generic_sparse` | `16.1.0.13.204885` | Catalog metadata/override for the 3B-backed natural-language Shortcuts “Ask AFM” action. |
| 62 | `com.apple.fm.language.instruct_3b.smart_naming.generic_sparse` | `16.0.0.13.103114` | Generates concise names/titles for content. |
| 63 | `com.apple.fm.language.instruct_3b.suggest_recipe_items.draft.generic_sparse` | `16.0.81624.13.204810` | Finds or suggests recipe items/ingredients from content. Draft companion used for low-latency speculative decoding. |
| 64 | `com.apple.fm.language.instruct_3b.suggest_recipe_items.generic_sparse` | `16.0.0.13.103112` | Finds or suggests recipe items/ingredients from content. |
| 65 | `com.apple.fm.language.instruct_3b.summarization.draft.generic_sparse` | `16.1.81624.13.204810` | General text summarization. Draft companion used for low-latency speculative decoding. |
| 66 | `com.apple.fm.language.instruct_3b.summarization.generic_sparse` | `16.1.0.13.103122` | General text summarization. |
| 67 | `com.apple.fm.language.instruct_3b.text_person_extraction.draft.generic_sparse` | `16.0.81624.13.204819` | Extracts person names/entities from text. Draft companion used for low-latency speculative decoding. |
| 68 | `com.apple.fm.language.instruct_3b.text_person_extraction.generic_sparse` | `16.0.0.13.103114` | Extracts person names/entities from text. |
| 69 | `com.apple.fm.language.instruct_3b.tokenizer.generic_sparse` | `16.0.0.13.204691` | Text tokenizer for the sparse 3B-active tier. |
| 70 | `com.apple.fm.language.instruct_3b.ui_grounding.generic_sparse` | `16.0.0.13.103114` | Grounds language to user-interface elements or references. |
| 71 | `com.apple.fm.language.instruct_3b.urgency_classification.generic_sparse` | `16.1.0.13.103145` | Classifies urgency for prioritization/routing. |
| 72 | `com.apple.fm.language.instruct_3b.voice.generic_sparse` | `16.0.0.13.103113` | Voice-related language processing adapter; exact subtask is not publicly documented. |
| 73 | `com.apple.fm.language.instruct_3b.voice2.generic_sparse` | `16.0.0.13.103113` | Second/revised voice-related language-processing adapter; exact subtask is not publicly documented. |
## On-device ~9M utility tier

| # | Asset specifier | Version | What it is for |
|---:|---|---|---|
| 74 | `com.apple.fm.language.instruct_9m.text_event_extraction_classifier.base.generic` | `1.2.81619.13.204726` | Tiny base model for extracting event-like information from text. |
| 75 | `com.apple.fm.language.instruct_9m.text_event_extraction_classifier.tokenizer.generic` | `1.1.0.13.204720` | Tokenizer for the tiny text-event-extraction classifier. |
## Speech components

| # | Asset specifier | Version | What it is for |
|---:|---|---|---|
| 76 | `com.apple.fm.speech.detokenizer_v1.generic` | `8.0.81624.13.204819` | Decodes speech-token streams in Apple’s speech synthesis/processing pipeline. |
| 77 | `com.apple.fm.speech.tokenizer_v1.generic_sparse` | `7.0.81624.13.204819` | Tokenizes speech/audio sequences for Apple’s speech pipeline. |
## Server/PCC feature adapters

| # | Asset specifier | Version | What it is for |
|---:|---|---|---|
| 78 | `com.apple.gm.server.instruct_server_v1.bullets_transform.generic` | `12.4.0.13.202298` | Server/PCC adapter that transforms prose into bullet points. |
| 79 | `com.apple.gm.server.instruct_server_v1.concise_tone.generic` | `11.0.0.13.202352` | Server/PCC adapter for concise writing tone. |
| 80 | `com.apple.gm.server.instruct_server_v1.fitness_workout_voice.generic` | `12.51.0.13.203500` | Server/PCC adapter for fitness/workout coaching voice and responses. |
| 81 | `com.apple.gm.server.instruct_server_v1.friendly_tone.generic` | `12.0.0.13.202237` | Server/PCC adapter for friendly writing tone. |
| 82 | `com.apple.gm.server.instruct_server_v1.magic_rewrite.generic` | `11.0.0.13.202352` | Server/PCC adapter for Writing Tools-style rewriting. |
| 83 | `com.apple.gm.server.instruct_server_v1.mail_reply_long_form_basic.generic` | `12.0.0.13.202237` | Server/PCC adapter for basic long-form Mail replies. |
| 84 | `com.apple.gm.server.instruct_server_v1.mail_reply_long_form_rewrite.generic` | `12.0.0.13.202237` | Server/PCC adapter for rewriting long-form Mail replies. |
| 85 | `com.apple.gm.server.instruct_server_v1.mail_reply_qa.generic` | `12.0.0.13.202237` | Server/PCC adapter for Mail reply question/answer generation. |
| 86 | `com.apple.gm.server.instruct_server_v1.open_ended_schema.generic` | `12.10.0.13.202386` | Server/PCC adapter for schema-constrained open-ended responses. |
| 87 | `com.apple.gm.server.instruct_server_v1.open_ended_tone.generic` | `12.24.0.13.202614` | Server/PCC adapter for applying tone to open-ended responses. |
| 88 | `com.apple.gm.server.instruct_server_v1.open_ended_tone_query_response.generic` | `12.0.0.13.202237` | Server/PCC adapter for answering an open-ended query with a tone/style. |
| 89 | `com.apple.gm.server.instruct_server_v1.open_ended_tone_query_response_v2.generic` | `12.0.0.13.202237` | Revised v2 server/PCC adapter for the same toned open-ended query/response path. |
| 90 | `com.apple.gm.server.instruct_server_v1.photos_memories_asset_curation_v2.generic` | `12.0.0.13.202237` | Server/PCC adapter for Photos Memories asset selection/curation. |
| 91 | `com.apple.gm.server.instruct_server_v1.photos_memories_global_traits_v2.generic` | `12.0.0.13.202237` | Server/PCC adapter for inferring global traits/themes of Photos Memories. |
| 92 | `com.apple.gm.server.instruct_server_v1.photos_memories_global_traits_v3.generic` | `12.0.0.13.202237` | Revised v3 server/PCC adapter for Photos Memories global-trait inference. |
| 93 | `com.apple.gm.server.instruct_server_v1.photos_memories_query_understanding_v3.generic` | `12.4.0.13.202298` | Server/PCC adapter for understanding natural-language Photos/Memories queries. |
| 94 | `com.apple.gm.server.instruct_server_v1.photos_memories_storyteller_v2.generic` | `12.0.0.13.202237` | Server/PCC adapter for narrating/storytelling around Photos Memories. |
| 95 | `com.apple.gm.server.instruct_server_v1.professional_tone.generic` | `12.0.0.13.202237` | Server/PCC adapter for professional writing tone. |
| 96 | `com.apple.gm.server.instruct_server_v1.reminders_auto_categorized_list.generic` | `12.0.0.13.202237` | Server/PCC adapter for turning content into categorized Reminders lists. |
| 97 | `com.apple.gm.server.instruct_server_v1.shortcuts_ask_afm_action.generic` | `11.19.0.13.202352` | Server/PCC adapter for natural-language Shortcuts actions. |
| 98 | `com.apple.gm.server.instruct_server_v1.shortcuts_ask_afm_action_v2.generic` | `12.54.0.13.203908` | Revised v2 server/PCC adapter for natural-language Shortcuts actions. |
| 99 | `com.apple.gm.server.instruct_server_v1.stx_multimodal.generic` | `12.20.0.13.202548` | Opaque internal multimodal server adapter; “stx” is not publicly expanded. |
| 100 | `com.apple.gm.server.instruct_server_v1.tables_transform.generic` | `12.0.0.13.202237` | Server/PCC adapter for transforming content into tables. |
| 101 | `com.apple.gm.server.instruct_server_v1.takeaways_transform.generic` | `12.0.0.13.202237` | Server/PCC adapter for extracting/formatting key takeaways. |
| 102 | `com.apple.gm.server.instruct_server_v1.text_summarizer.generic` | `12.0.0.13.202237` | Server/PCC adapter for text summarization. |
## Translation components

| # | Asset specifier | Version | What it is for |
|---:|---|---|---|
| 103 | `com.apple.gm.translate_fm.machine_translation.alignment.generic` | `14.2.0.13.204469` | Translation support data/model component for phrase/word alignment. |
| 104 | `com.apple.gm.translate_fm.machine_translation.phrasebook.generic` | `15.0.0.13.204592` | Translation support data/model component containing phrasebook/translation-memory behavior. |
## Guard configurations

| # | Asset specifier | Version | What it is for |
|---:|---|---|---|
| 105 | `com.apple.mm_guard.output.configuration.generic` | `0.0.4.13.204660` | Output-safety guard configuration for multimodal generation; configuration, not a standalone model. |
| 106 | `com.apple.safety.output.configuration.generic` | `0.1.13.13.204658` | General output-safety guard configuration; configuration, not a standalone model. |
