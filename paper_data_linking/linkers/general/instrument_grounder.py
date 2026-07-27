import logging
import os
import re
import time
from typing import List, Dict, Optional

from paper_data_linking.clients.litellm_client import LiteLLMClient
from paper_data_linking.linkers.general.normalizers.normalizer import NormalizedInstrument
from paper_data_linking.pipeline_context import node_stage
from .finders import AbstractInstrumentFinder
from .catalogue_models import CatalogueEntry, Mission
from .prompt_loader import load_and_render_prompt

logger = logging.getLogger(__name__)


class DebugLogger:
    """Helper class for structured debug logging with verbosity control"""
    
    @staticmethod
    def is_verbose() -> bool:
        """Check if verbose debug logging is enabled via environment variable"""
        return os.getenv('DEBUG_INSTRUMENT_GROUNDING_VERBOSE', 'false').lower() == 'true'
    
    # For backward compatibility, maintain VERBOSE property
    @property
    def VERBOSE(self) -> bool:
        return DebugLogger.is_verbose()
    
    @staticmethod
    def log_candidates(candidates: List[Dict], similarities: List[float], stage: str, limit: int = None):
        """Log candidates with their similarities in a structured way"""
        display_candidates = candidates[:limit] if limit else candidates
        display_similarities = similarities[:limit] if limit and similarities else similarities
        
        candidate_lines = [f"=== {stage.upper()} CANDIDATES ==="]
        for i, (candidate, sim) in enumerate(zip(display_candidates, display_similarities)):
            candidate_lines.append(f"  {i+1:2d}. {candidate['instrument_code']:8s}/{candidate['mission_code']:10s} "
                                  f"(sim: {sim:.4f}) - {candidate.get('description', 'No description')[:80]}...")
        
        if limit and len(candidates) > limit:
            candidate_lines.append(f"  ... and {len(candidates) - limit} more candidates")
            
        logger.info('\n'.join(candidate_lines))
    
    @staticmethod
    def log_openai_request(messages: List[Dict], model: str, temperature: float, max_tokens: int):
        """Log OpenAI request with verbosity control"""
        if not DebugLogger.is_verbose():
            # Concise logging
            logger.info(f"🤖 LLM Call: {model} (temp={temperature}, max_tokens={max_tokens})")
            return
            
        # Verbose logging (original behavior)
        request_lines = [
            f"=== OPENAI REQUEST ===",
            f"Model: {model}",
            f"Temperature: {temperature}",
            f"Max tokens: {max_tokens}",
            f"Messages:"
        ]
        
        for i, message in enumerate(messages):
            role = message.get('role', 'unknown')
            content = message.get('content', '')
            request_lines.append(f"  Message {i+1} ({role}):")
            
            # Show complete content for debugging - no truncation
            lines = content.split('\n')
            for line in lines:
                request_lines.append(f"    {line}")
                
        logger.info('\n'.join(request_lines))
    
    @staticmethod
    def log_openai_response(response, response_type: str = "chat"):
        """Log OpenAI response with verbosity control"""
        if not DebugLogger.is_verbose():
            # Concise logging
            if response_type == "chat" and hasattr(response, 'choices') and response.choices:
                choice = response.choices[0]
                content_preview = choice.message.content[:100] + "..." if len(choice.message.content) > 100 else choice.message.content
                logger.info(f"📤 LLM Response: {content_preview} (reason: {choice.finish_reason})")
            return
            
        # Verbose logging (original behavior)
        response_lines = [f"=== OPENAI RESPONSE ({response_type.upper()}) ==="]
        
        if response_type == "chat":
            if hasattr(response, 'choices') and response.choices:
                choice = response.choices[0]
                response_lines.append(f"Finish reason: {choice.finish_reason}")
                if hasattr(choice.message, 'content'):
                    response_lines.append(f"Content: {choice.message.content}")
                # Note: LiteLLM doesn't have .parsed attribute, structured output is in .content
        elif response_type == "embedding":
            response_lines.append(f"Embedding dimensions: {len(response.data[0].embedding)}")
            response_lines.append(f"First 5 values: {response.data[0].embedding[:5]}")
        
        if hasattr(response, 'usage'):
            response_lines.append(f"Token usage: {response.usage}")
            
        logger.info('\n'.join(response_lines))
    
    @staticmethod
    def log_query_context(instrument_entry: Dict):
        """Log the input instrument entry with verbosity control"""
        if not DebugLogger.is_verbose():
            # Concise logging
            name = instrument_entry.get('name', 'N/A')
            periods_count = len(instrument_entry.get('data_collection_periods', []))
            logger.info(f"🔍 Grounding: {name} ({periods_count} data periods)")
            return
            
        # Verbose logging (original behavior)
        context_lines = [
            f"=== INPUT INSTRUMENT ENTRY ===",
            f"Name: {instrument_entry.get('name', 'N/A')}",
            f"General comments: {instrument_entry.get('general_comments', 'N/A')}"
        ]
        
        periods = instrument_entry.get('data_collection_periods', [])
        if periods:
            context_lines.append(f"Data collection periods ({len(periods)}):")
            for i, period in enumerate(periods, 1):
                context_lines.append(f"  Period {i}:")
                context_lines.append(f"    Time range: {period.get('time_range', 'N/A')}")
                context_lines.append(f"    Wavelengths: {period.get('wavelengths', 'N/A')}")
                context_lines.append(f"    Physical observable: {period.get('physical_observable', 'N/A')}")
                if period.get('additional_comments'):
                    context_lines.append(f"    Additional comments: {period['additional_comments']}")
        else:
            context_lines.append("No data collection periods")
            
        logger.info('\n'.join(context_lines))


class InstrumentGrounder:
    """
    Grounds instrument names using a provided finder and LLM validation.
    Uses hierarchical approach: first identify missions, then match instruments within those missions.
    """

    def __init__(
        self, 
        finder: AbstractInstrumentFinder, 
        llm_client: Optional[LiteLLMClient] = None,
        llm_config=None
    ):
        from paper_data_linking.config.settings import LLMPipelineConfig
        self.finder = finder
        self.llm_client = llm_client or LiteLLMClient()
        if llm_config is None:
            raise ValueError("llm_config is required - no fallback to default to ensure explicit configuration")
        if not isinstance(llm_config, LLMPipelineConfig):
            raise ValueError(f"llm_config must be LLMPipelineConfig, got {type(llm_config)}")
        self.llm_config = llm_config

    def _build_context_for_llm(self, instrument_entry: dict) -> str:
        """Build comprehensive context for LLM grounding.

        Renders the structured instrument entry as the description string the
        grounding LLM sees. Includes every populated supporting-quote field so
        discriminating identifiers buried in quotes (e.g., spacecraft variant
        suffixes, sub-instrument names, dataset filenames) reach the model.
        """

        context_lines = [
            f"Instrument Name: {instrument_entry['name']}",
            f"General Comments: {instrument_entry.get('general_comments', '')}",
        ]

        # Suite-level supporting quotes, if any.
        for q in instrument_entry.get("general_quotes") or []:
            context_lines.append(f'  Supporting Quote: "{q}"')

        for i, period in enumerate(instrument_entry.get("data_collection_periods", []), 1):
            context_lines.append(f"\nData Collection Period {i}:")
            context_lines.append(f"  Time Range: {period.get('time_range', 'Not specified')}")
            for q in period.get("time_quotes") or []:
                context_lines.append(f'    Time Supporting Quote: "{q}"')
            context_lines.append(f"  Wavelengths: {period.get('wavelengths', 'Not specified')}")
            for q in period.get("wavelength_quotes") or []:
                context_lines.append(f'    Wavelength Supporting Quote: "{q}"')
            context_lines.append(f"  Physical Observable: {period.get('physical_observable', 'Not specified')}")
            for q in period.get("physobs_quotes") or []:
                context_lines.append(f'    Physical Observable Supporting Quote: "{q}"')
            if period.get("additional_comments"):
                context_lines.append(f"  Additional Comments: {period['additional_comments']}")
            for q in period.get("general_quotes") or []:
                context_lines.append(f'    Supporting Quote: "{q}"')

        return "\n".join(context_lines)

    def _extract_mission_context(self, instrument_entry: dict) -> str:
        """Extract mission-focused context from instrument entry.

        Includes supporting quotes so spacecraft variant identifiers (e.g.
        "MMS2", "STEREO-A", "Cluster-1") buried in quotes can disambiguate
        the mission_selection / mission_validation decisions. Without them,
        a section title generalized to family level (e.g. "FGM on board
        MMS") leads to constellation fanout.
        """
        context_lines = [
            f"Instrument: {instrument_entry.get('name', 'N/A')}",
            f"Context: {instrument_entry.get('general_comments', 'N/A')}",
        ]

        for q in instrument_entry.get("general_quotes") or []:
            context_lines.append(f'Supporting Quote: "{q}"')

        # Add time periods which might contain mission info
        periods = instrument_entry.get('data_collection_periods', [])
        if periods:
            for i, period in enumerate(periods, 1):
                time_range = period.get('time_range', '')
                if time_range:
                    context_lines.append(f"Time period {i}: {time_range}")
                additional = period.get('additional_comments', '')
                if additional:
                    context_lines.append(f"Additional info {i}: {additional}")
                # Quotes attached to the period — variant identifiers often
                # appear here (e.g., paper attributes a measurement to a
                # specific spacecraft in a physobs or general quote).
                for qfield in ("time_quotes", "physobs_quotes", "wavelength_quotes", "general_quotes"):
                    for q in period.get(qfield) or []:
                        context_lines.append(f'Supporting Quote {i}: "{q}"')

        return "\n".join(context_lines)

    def _get_unique_missions(self) -> List[Mission]:
        """Get unique missions from finder (cached by finder implementation)."""
        return self.finder.get_unique_missions()
    
    def _get_unique_missions_for_data_system(self, data_system: str) -> List[Mission]:
        """Get unique missions for a specific data system."""
        return self.finder.get_missions_for_data_system(data_system)

    def _identify_missions_with_nano(self, instrument_entry: dict, top_k: int = 10) -> List[str]:
        """
        Stage 1: Use GPT-4.1-mini to identify top 10 candidate missions by index.
        """
        mission_context = self._extract_mission_context(instrument_entry)
        
        # Get all available missions
        all_missions = self._get_unique_missions()
        # Sort by mission name for consistency
        sorted_missions = sorted(all_missions, key=lambda m: m.mission_name)

        mission_info = [
            f"=== MISSION IDENTIFICATION (INDEXED) ===",
            f"Looking for missions that might host: {instrument_entry.get('name', 'N/A')}",
            f"Context: {mission_context}",
            f"Available missions: {len(sorted_missions)} unique missions"
        ]
        logger.info('\n'.join(mission_info))

        # Create numbered mission list for prompt - include code, name, and description
        missions_numbered = []
        for i, mission in enumerate(sorted_missions, 1):  # 1-indexed for LLM
            entry = f"{i}. {mission.mission_code} ({mission.mission_name})"
            if mission.description:
                entry += f" — {mission.description}"
            missions_numbered.append(entry)
        missions_text = "\n".join(missions_numbered)
        
        # Load prompts from XML template
        template_name = "mission_identification"
        system_msg, user_msg = load_and_render_prompt(
            template_name,
            mission_context=mission_context,
            missions_text=missions_text,
            mission_count=len(sorted_missions),
            top_k=top_k
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ]

        # Capture template variables for render_context
        prompt_context = {
            'template_name': template_name,
            'mission_context': mission_context,
            'missions_text': missions_text,
            'mission_count': len(sorted_missions),
            'top_k': top_k
        }

        # Log the mission identification request
        config = self.llm_config.instrument_grounding.similarity_filter
        DebugLogger.log_openai_request(messages, config.model, config.temperature, config.max_tokens)

        max_retries = 2
        for attempt in range(max_retries):
            try:
                config = self.llm_config.instrument_grounding.similarity_filter
                response = self.llm_client.completion(
                    call_type="mission_identification",
                    model=config.model,
                    messages=messages,
                    **config.to_kwargs(prompt_context=prompt_context)
                )
                
                # Log the response
                DebugLogger.log_openai_response(response, "chat")
                
                nano_response = response.choices[0].message.content.strip()
                
                # Parse mission indices from response
                if nano_response.upper() == "UNKNOWN":
                    logger.info("Mission identification: UNKNOWN (too generic/unclear)")
                    return []
                
                # Parse the model's "ShortCode(index)" pairs. The model reliably NAMES
                # the mission in the token but occasionally miscounts the 1-based index
                # by ±1 (issue #170) — and since adjacent missions can be unrelated
                # (e.g. "Parker Solar Probe"(266) vs "Pello Geophysical Observatory"(267)),
                # a bare-index lookup then resolves to the wrong mission. So we trust the
                # token to validate the index and correct off-by-one errors.
                import re
                pairs = re.findall(r'([^,()]+?)\s*\((\d+)\)', nano_response)
                mission_indices = []

                if pairs:
                    for token, num_str in pairs[:top_k]:
                        index_0based = int(num_str) - 1
                        resolved = self._resolve_mission_index(token, index_0based, sorted_missions)
                        if resolved is not None:
                            mission_indices.append(resolved)
                        else:
                            logger.warning(f"Could not resolve mission token={token!r} index={num_str}")
                else:
                    # No "Name(index)" pairs — fall back to bare-number extraction (legacy).
                    for num_str in re.findall(r'\b(\d+)\b', nano_response)[:top_k]:
                        index_0based = int(num_str) - 1
                        if 0 <= index_0based < len(sorted_missions):
                            mission_indices.append(index_0based)
                        else:
                            logger.warning(f"Invalid mission index: {num_str} (out of range 1-{len(sorted_missions)})")

                # Get actual mission names
                selected_missions = [sorted_missions[i].mission_name for i in mission_indices]

                result_info = [
                    f"Mission identification result: {nano_response}",
                    f"Parsed indices (1-based): {[i+1 for i in mission_indices]}",
                    f"Selected missions: {selected_missions}"
                ]
                logger.info('\n'.join(result_info))
                
                return selected_missions
                
            except Exception as e:
                logger.error(f"Mission identification failed on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    continue
        
        logger.warning("Mission identification failed after all retries")
        return []

    @staticmethod
    def _norm_token(s: str) -> str:
        """Normalise a mission identifier for fuzzy matching: uppercase, alnum only."""
        import re
        return re.sub(r'[^A-Z0-9]', '', (s or '').upper())

    def _resolve_mission_index(self, token: str, index_0based: int, sorted_missions) -> Optional[int]:
        """Resolve the mission the model meant from its 'token(index)' answer.

        The model reliably NAMES the mission in `token` but occasionally writes a
        1-based index that is off by ±1 (issue #170). We therefore:
          1. trust the index when the token is consistent with the mission there;
          2. otherwise correct an off-by-one by checking the immediate neighbours;
          3. otherwise keep the index if it is in range (never worse than before),
             or, if out of range, fall back to a token search over all missions.
        Returns a 0-based index, or None if nothing resolves.
        """
        nt = self._norm_token(token)
        n = len(sorted_missions)

        def matches(i: int) -> bool:
            if not (0 <= i < n) or not nt:
                return False
            m = sorted_missions[i]
            nn = self._norm_token(m.mission_name)
            seg = self._norm_token((m.mission_code or '').rstrip('/').split('/')[-1])
            if nt == nn or nt == seg:
                return True
            # the model may write an abbreviation that is a substring of the canonical
            # name/segment (e.g. 'DSCOVR' in the full name). Only the token ⊆ candidate
            # direction is safe — the reverse mis-matches neighbours (e.g. 'PARK' ⊆
            # 'PARKERSOLARPROBE'). Require length ≥3 to avoid spurious short matches.
            return len(nt) >= 3 and (nt in nn or nt in seg)

        if 0 <= index_0based < n:
            if matches(index_0based):
                return index_0based
            # off-by-one (the observed #170 failure): prefer the neighbour named
            for nb in (index_0based - 1, index_0based + 1):
                if matches(nb):
                    logger.info(
                        f"Corrected mission index off-by-one for token={token!r}: "
                        f"{sorted_missions[index_0based].mission_name!r} -> "
                        f"{sorted_missions[nb].mission_name!r}"
                    )
                    return nb
            # token doesn't match index or neighbours — keep the index (legacy behaviour)
            return index_0based

        # index out of range — the number is useless; try to find the mission by name
        for i in range(n):
            if matches(i):
                return i
        return None

    def _identify_missions_with_nano_for_data_system(self, instrument_entry: dict, data_system: str, top_k: int = 10) -> List[str]:
        """
        Stage 1: Use GPT-4.1-mini to identify top 10 candidate missions by index for a specific data system.
        """
        mission_context = self._extract_mission_context(instrument_entry)
        
        # Get missions for specific data system
        data_system_missions = self._get_unique_missions_for_data_system(data_system)
        # Sort by mission name for consistency
        sorted_missions = sorted(data_system_missions, key=lambda m: m.mission_name)

        if not sorted_missions:
            logger.warning(f"No missions found for data system {data_system}")
            return []

        mission_info = [
            f"=== MISSION IDENTIFICATION ({data_system.upper()}) (INDEXED) ===",
            f"Looking for missions that might host: {instrument_entry.get('name', 'N/A')}",
            f"Context: {mission_context}",
            f"Available missions in {data_system}: {len(sorted_missions)} unique missions"
        ]
        logger.info('\n'.join(mission_info))

        # Create numbered mission list for prompt - include code, name, and description
        missions_numbered = []
        for i, mission in enumerate(sorted_missions, 1):  # 1-indexed for LLM
            entry = f"{i}. {mission.mission_code} ({mission.mission_name})"
            if mission.description:
                entry += f" — {mission.description}"
            missions_numbered.append(entry)
        missions_text = "\n".join(missions_numbered)
        
        # Load prompts from XML template
        template_name = "mission_identification"
        system_msg, user_msg = load_and_render_prompt(
            template_name,
            mission_context=mission_context,
            missions_text=missions_text,
            mission_count=len(sorted_missions),
            top_k=top_k
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ]

        # Capture template variables for render_context
        prompt_context = {
            'template_name': template_name,
            'mission_context': mission_context,
            'missions_text': missions_text,
            'mission_count': len(sorted_missions),
            'top_k': top_k
        }

        # Log the mission identification request
        config = self.llm_config.instrument_grounding.similarity_filter
        DebugLogger.log_openai_request(messages, config.model, config.temperature, config.max_tokens)

        max_retries = 2
        for attempt in range(max_retries):
            try:
                config = self.llm_config.instrument_grounding.similarity_filter
                response = self.llm_client.completion(
                    call_type="mission_identification",
                    model=config.model,
                    messages=messages,
                    **config.to_kwargs(prompt_context=prompt_context)
                )
                
                # Log the response
                DebugLogger.log_openai_response(response, "chat")
                
                nano_response = response.choices[0].message.content.strip()
                
                # Parse mission indices from response
                if nano_response.upper() == "UNKNOWN":
                    logger.info(f"Mission identification in {data_system}: UNKNOWN (too generic/unclear)")
                    return []
                
                # Parse the model's "ShortCode(index)" pairs. The model reliably NAMES
                # the mission in the token but occasionally miscounts the 1-based index
                # by ±1 (issue #170) — and since adjacent missions can be unrelated
                # (e.g. "Parker Solar Probe"(266) vs "Pello Geophysical Observatory"(267)),
                # a bare-index lookup then resolves to the wrong mission. So we trust the
                # token to validate the index and correct off-by-one errors.
                import re
                pairs = re.findall(r'([^,()]+?)\s*\((\d+)\)', nano_response)
                mission_indices = []

                if pairs:
                    for token, num_str in pairs[:top_k]:
                        index_0based = int(num_str) - 1
                        resolved = self._resolve_mission_index(token, index_0based, sorted_missions)
                        if resolved is not None:
                            mission_indices.append(resolved)
                        else:
                            logger.warning(f"Could not resolve mission token={token!r} index={num_str}")
                else:
                    # No "Name(index)" pairs — fall back to bare-number extraction (legacy).
                    for num_str in re.findall(r'\b(\d+)\b', nano_response)[:top_k]:
                        index_0based = int(num_str) - 1
                        if 0 <= index_0based < len(sorted_missions):
                            mission_indices.append(index_0based)
                        else:
                            logger.warning(f"Invalid mission index: {num_str} (out of range 1-{len(sorted_missions)})")

                # Get actual mission names
                selected_missions = [sorted_missions[i].mission_name for i in mission_indices]

                result_info = [
                    f"Mission identification result in {data_system}: {nano_response}",
                    f"Parsed indices (1-based): {[i+1 for i in mission_indices]}",
                    f"Selected missions: {selected_missions}"
                ]
                logger.info('\n'.join(result_info))
                
                return selected_missions
                
            except Exception as e:
                logger.error(f"Mission identification failed in {data_system} on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    continue
        
        logger.warning(f"Mission identification failed in {data_system} after all retries")
        return []

    def _select_final_mission(self, instrument_entry: dict, candidate_missions: List[str]) -> Optional[List[str]]:
        """
        Stage 2: Use GPT-4.1 to select mission(s) from candidates by index.
        Always returns a list of mission names, or None if no valid missions found.
        """
        if not candidate_missions:
            return None
            
        if len(candidate_missions) == 1:
            logger.info(f"Only one candidate mission: {candidate_missions[0]}")
            return [candidate_missions[0]]
        
        mission_context = self._extract_mission_context(instrument_entry)
        
        mission_info = [
            f"=== FINAL MISSION SELECTION ===",
            f"Selecting final mission from {len(candidate_missions)} candidates"
        ]
        logger.info('\n'.join(mission_info))

        # Look up Mission objects to get both code and full name
        all_missions = self._get_unique_missions()
        mission_lookup = {m.mission_name: m for m in all_missions}

        # Create numbered candidate list with code, name, and description
        candidates_numbered = []
        for i, mission_name in enumerate(candidate_missions, 1):  # 1-indexed for LLM
            mission_obj = mission_lookup.get(mission_name)
            if mission_obj:
                entry = f"{i}. {mission_obj.mission_code} ({mission_obj.mission_name})"
                if mission_obj.description:
                    entry += f" — {mission_obj.description}"
                candidates_numbered.append(entry)
            else:
                # Fallback to just name if lookup fails
                candidates_numbered.append(f"{i}. {mission_name}")
        candidates_text = "\n".join(candidates_numbered)
        
        # Load prompts from XML template
        template_name = "mission_selection"
        system_msg, user_msg = load_and_render_prompt(
            template_name,
            mission_context=mission_context,
            candidates_text=candidates_text,
            candidate_count=len(candidate_missions)
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ]

        # Capture template variables for render_context
        prompt_context = {
            'template_name': template_name,
            'mission_context': mission_context,
            'candidates_text': candidates_text,
            'candidate_count': len(candidate_missions)
        }

        # Log the request
        config = self.llm_config.instrument_grounding.exact_match
        DebugLogger.log_openai_request(messages, config.model, config.temperature, config.max_tokens)

        max_retries = 2
        for attempt in range(max_retries):
            try:
                response = self.llm_client.completion(
                    call_type="mission_selection",
                    model=config.model,
                    messages=messages,
                    **config.to_kwargs(prompt_context=prompt_context)
                )
                
                # Log the response
                DebugLogger.log_openai_response(response, "chat")
                
                gpt4_response = response.choices[0].message.content.strip()
                
                # Parse comma-separated indices (e.g., "1,3" or "2")
                import re
                numbers = re.findall(r'\b(\d+)\b', gpt4_response)
                if not numbers:
                    logger.warning(f"No valid numbers found in response: {gpt4_response}")
                    continue
                
                # Check for uncertainty response
                if numbers[0] == '0':
                    logger.info(f"LLM indicated uncertainty/ambiguity: {gpt4_response}")
                    return None
                
                # Convert all numbers to mission names
                valid_missions = []
                valid_indices = []
                
                for num_str in numbers:
                    index_1based = int(num_str)
                    index_0based = index_1based - 1  # Convert to 0-based
                    
                    if 0 <= index_0based < len(candidate_missions):
                        valid_missions.append(candidate_missions[index_0based])
                        valid_indices.append(index_1based)
                    else:
                        logger.warning(f"Invalid mission index: {index_1based} (out of range 1-{len(candidate_missions)})")
                
                if valid_missions:
                    result_info = [
                        f"Final mission selection: {gpt4_response}",
                        f"Selected indices (1-based): {valid_indices}",
                        f"Selected missions: {', '.join(valid_missions)}"
                    ]
                    logger.info('\n'.join(result_info))
                    
                    return valid_missions
                else:
                    logger.warning(f"No valid mission indices found in response: {gpt4_response}")
                    
            except Exception as e:
                logger.error(f"Final mission selection failed on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    continue
        
        # logger.warning("Final mission selection failed, using first candidate")
        # return candidate_missions[0] if candidate_missions else None
        return None

    def _select_final_instrument(self, instrument_entry: dict, filtered_instruments: List[CatalogueEntry]) -> Optional[List[CatalogueEntry]]:
        """
        Stage 3: Use GPT-4.1 to select final instrument(s) from filtered list by index.
        Always returns List[Dict] for consistency, or None if no matches found.
        """
        if not filtered_instruments:
            return None
            
        if len(filtered_instruments) == 1:
            logger.info(f"Only one candidate instrument: {filtered_instruments[0].instrument_code}")
            return [filtered_instruments[0]]  # Always return list for consistency
        
        full_context = self._build_context_for_llm(instrument_entry)
        
        instrument_info = [
            f"=== FINAL INSTRUMENT SELECTION ===",
            f"Selecting final instrument from {len(filtered_instruments)} candidates"
        ]
        logger.info('\n'.join(instrument_info))
        
        # Create numbered instrument list
        instruments_numbered = []
        for i, inst in enumerate(filtered_instruments, 1):  # 1-indexed for LLM
            name_prefix = f"[{inst.instrument_name}] " if inst.instrument_name else ""
            instruments_numbered.append(f"{i}. {name_prefix}{inst.description} [{inst.instrument_code}/{inst.mission_code}]")
        instruments_text = "\n".join(instruments_numbered)

        # Log the complete candidate instruments list
        candidate_debug = [
            f"=== CANDIDATE INSTRUMENTS FOR FINAL SELECTION ===",
            f"Total candidates: {len(filtered_instruments)}",
            f"Candidate list being sent to LLM:"
        ]
        candidate_debug.extend([f"  {line}" for line in instruments_numbered])
        logger.info('\n'.join(candidate_debug))
        
        # Load prompts from XML template
        template_name = "instrument_selection"
        system_msg, user_msg = load_and_render_prompt(
            template_name,
            full_context=full_context,
            instruments_text=instruments_text,
            instrument_count=len(filtered_instruments)
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ]

        # Capture template variables for render_context
        prompt_context = {
            'template_name': template_name,
            'full_context': full_context,
            'instruments_text': instruments_text,
            'instrument_count': len(filtered_instruments)
        }

        # Log the request
        config = self.llm_config.instrument_grounding.exact_match_fallback
        DebugLogger.log_openai_request(messages, config.model, config.temperature, config.max_tokens)

        max_retries = 2
        for attempt in range(max_retries):
            try:
                response = self.llm_client.completion(
                    call_type="instrument_selection",
                    model=config.model,
                    messages=messages,
                    **config.to_kwargs(prompt_context=prompt_context)
                )
                
                # Log the response
                DebugLogger.log_openai_response(response, "chat")
                
                gpt4_response = response.choices[0].message.content.strip()
                
                # Parse comma-separated indices (e.g., "1,3" or "2")
                import re
                numbers = re.findall(r'\b(\d+)\b', gpt4_response)
                if not numbers:
                    logger.warning(f"No valid numbers found in response: {gpt4_response}")
                    continue
                
                # Check for uncertainty response
                if numbers[0] == '0':
                    logger.info(f"LLM indicated uncertainty/ambiguity: {gpt4_response}")
                    return None
                
                # Convert all numbers to instruments
                valid_instruments = []
                valid_indices = []
                
                for num_str in numbers:
                    index_1based = int(num_str)
                    index_0based = index_1based - 1  # Convert to 0-based
                    
                    if 0 <= index_0based < len(filtered_instruments):
                        valid_instruments.append(filtered_instruments[index_0based])
                        valid_indices.append(index_1based)
                    else:
                        logger.warning(f"Invalid instrument index: {index_1based} (out of range 1-{len(filtered_instruments)})")
                
                if valid_instruments:
                    result_info = [
                        f"Final instrument selection: {gpt4_response}",
                        f"Selected indices (1-based): {valid_indices}",
                        f"Selected instruments: {', '.join([f'{inst.instrument_code}/{inst.mission_code}' for inst in valid_instruments])}"
                    ]
                    logger.info('\n'.join(result_info))
                    
                    return valid_instruments
                else:
                    logger.warning(f"No valid instrument indices found in response: {gpt4_response}")
                    
            except Exception as e:
                logger.error(f"Final instrument selection failed on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    continue
        
        # logger.warning("Final instrument selection failed, using first candidate")
        # return filtered_instruments[0] if filtered_instruments else None
        return None

    def _identify_multiple_valid_matches(self, instrument_entry: dict, filtered_instruments: List[CatalogueEntry]) -> Optional[List[CatalogueEntry]]:
        """
        When LLM indicates ambiguity (returns 0), ask it to identify ALL instruments that could be valid matches.
        This handles cases like STEREO-A vs STEREO-B where both are legitimate possibilities.
        """
        if len(filtered_instruments) < 2:
            return None  # Need at least 2 candidates for ambiguity
        
        full_context = self._build_context_for_llm(instrument_entry)
        
        # Create numbered instrument list
        instruments_numbered = []
        for i, inst in enumerate(filtered_instruments, 1):  # 1-indexed for LLM
            name_prefix = f"[{inst.instrument_name}] " if inst.instrument_name else ""
            instruments_numbered.append(f"{i}. {name_prefix}{inst.description} [{inst.instrument_code}/{inst.mission_code}]")
        instruments_text = "\n".join(instruments_numbered)

        logger.info(f"=== IDENTIFYING MULTIPLE VALID MATCHES ===")
        logger.info(f"Checking {len(filtered_instruments)} candidates for multiple valid matches")
        
        # Load prompts from XML template
        template_name = "multiple_matches"
        system_msg, user_msg = load_and_render_prompt(
            template_name,
            full_context=full_context,
            instruments_text=instruments_text
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ]

        # Capture template variables for render_context
        prompt_context = {
            'template_name': template_name,
            'full_context': full_context,
            'instruments_text': instruments_text
        }

        # Log the request
        config = self.llm_config.instrument_grounding.substring_filter
        DebugLogger.log_openai_request(messages, config.model, config.temperature, config.max_tokens)

        try:
            response = self.llm_client.completion(
                call_type="instrument_multiple_selection",
                model=config.model,
                messages=messages,
                **config.to_kwargs(prompt_context=prompt_context)
            )
                
            # Log the response
            DebugLogger.log_openai_response(response, "chat")
            
            gpt4_response = response.choices[0].message.content.strip()
            
            # Parse multiple indices
            import re
            numbers = re.findall(r'\b(\d+)\b', gpt4_response)
            if numbers:
                valid_indices = []
                valid_instruments = []
                
                for num_str in numbers:
                    index_1based = int(num_str)
                    index_0based = index_1based - 1
                    
                    if 0 <= index_0based < len(filtered_instruments):
                        valid_indices.append(index_1based)
                        valid_instruments.append(filtered_instruments[index_0based])
                
                if len(valid_instruments) > 1:
                    logger.info(f"Multiple valid matches identified: {valid_indices}")
                    for i, inst in enumerate(valid_instruments):
                        logger.info(f"  Match {i+1}: {inst.instrument_code}/{inst.mission_code}")
                    return valid_instruments
                elif len(valid_instruments) == 1:
                    logger.info(f"Single valid match identified: {valid_indices[0]}")
                    return valid_instruments  # Return list for consistency
                else:
                    logger.warning("No valid instruments identified in multiple match check")
                    return None
            else:
                logger.warning(f"No valid numbers found in multiple match response: {gpt4_response}")
                return None
                
        except Exception as e:
            logger.error(f"Multiple match identification failed: {e}")
            return None

    def _filter_catalog_by_mission_names(self, mission_names: List[str]) -> List[CatalogueEntry]:
        """
        Filter the catalog to only instruments from specified missions using efficient finder method.
        """
        if not mission_names:
            return []
        
        # Use the finder's efficient filtering method
        filtered_instruments = self.finder.get_instruments_for_missions(mission_names)
        
        filter_info = [
            f"=== MISSION FILTERING ===",
            f"Filtering catalog by {len(mission_names)} candidate missions",
            f"Missions: {', '.join(mission_names)}",
            f"Filtered catalog: {len(filtered_instruments)} instruments",
            f"",
            f"Filtered instruments:"
        ]
        
        # Add each filtered instrument to the log using model attributes
        for i, inst in enumerate(filtered_instruments, 1):
            filter_info.append(f"  {i:2d}. {inst.instrument_code} / {inst.mission_code}")
            filter_info.append(f"      Name: {inst.instrument_name}")
            filter_info.append(f"      Description: {inst.description[:100]}...")
            
        logger.info('\n'.join(filter_info))
        
        return filtered_instruments
    
    def _filter_catalog_by_mission_names_for_data_system(self, mission_names: List[str], data_system: str) -> List[CatalogueEntry]:
        """
        Filter the catalog to only instruments from specified missions within a specific data system.
        """
        if not mission_names or not data_system:
            return []
        
        # Use the finder's data-system-specific filtering method
        filtered_instruments = self.finder.get_instruments_for_missions_and_data_system(mission_names, data_system)
        
        filter_info = [
            f"=== MISSION FILTERING ({data_system.upper()}) ===",
            f"Filtering by {len(mission_names)} missions in {data_system}",
            f"Missions: {', '.join(mission_names)}",
            f"Filtered catalog: {len(filtered_instruments)} instruments",
            f"",
            f"Filtered instruments:"
        ]
        
        # Add each filtered instrument to the log using model attributes
        for i, inst in enumerate(filtered_instruments, 1):
            filter_info.append(f"  {i:2d}. {inst.instrument_code} / {inst.mission_code}")
            filter_info.append(f"      Name: {inst.instrument_name}")
            filter_info.append(f"      Description: {inst.description[:100]}...")
            
        logger.info('\n'.join(filter_info))
        
        return filtered_instruments

    def ground_instrument(self, instrument_entry: dict) -> Optional[List[CatalogueEntry]]:
        """
        Ground an instrument entry across all available data systems in parallel.
        Always returns List[CatalogueEntry] for consistency, or None if no matches found.
        """
        instrument_name = instrument_entry.get("name", "Unknown")
        
        start_info = [
            f"🎯 Starting parallel grounding for: {instrument_name}",
            f"=" * 80
        ]
        logger.info('\n'.join(start_info))
        
        # Log the input entry in detail
        DebugLogger.log_query_context(instrument_entry)
        
        return self._ground_instrument_parallel(instrument_entry)

    def _ground_instrument_hierarchical(self, instrument_entry: dict) -> Optional[List[CatalogueEntry]]:
        """
        Systematic hierarchical grounding using indexed LLM approach:
        1. GPT-4.1-mini identifies top 10 candidate missions by index
        2. GPT-4.1 selects ONE final mission by index
        3. Filter catalog to instruments from selected mission
        4. GPT-4.1 selects ONE final instrument by index
        """
        
        # Stage 1: Get top 10 candidate missions by index
        candidate_mission_names = self._identify_missions_with_nano(instrument_entry, top_k=10)
        
        if not candidate_mission_names:
            logger.warning("No candidate missions identified - too generic or unclear")
            return None
        
        # Stage 2: Select final mission(s) by index
        selected_missions = self._select_final_mission(instrument_entry, candidate_mission_names)
        
        if not selected_missions:
            logger.warning("No final missions selected - description too ambiguous to disambiguate")
            return None

        # Stage 2.5: Validate selected mission(s)
        # Use first available data system for lookup (hierarchical method is cross-system)
        all_missions = self._get_unique_missions()
        ds_for_validation = all_missions[0].data_system if all_missions else "vso"
        validated_missions = self._validate_missions(instrument_entry, selected_missions, ds_for_validation)

        if not validated_missions:
            logger.warning("No missions passed validation")
            return None

        selected_missions = validated_missions

        # Stage 3: Filter catalog by selected mission(s)
        filtered_catalog = self._filter_catalog_by_mission_names(selected_missions)
        
        if not filtered_catalog:
            mission_names_str = ', '.join(selected_missions)
            logger.warning(f"No instruments found in selected missions: {mission_names_str}")
            return None
        
        # Stage 4: Select ONE final instrument by index
        selected_result = self._select_final_instrument(instrument_entry, filtered_catalog)
        
        if not selected_result:
            logger.warning("No final instrument selected - multiple instruments could match equally")
            return None
        
        # selected_result is now always List[CatalogueEntry] (no need for isinstance check)
        logger.info(f"Found {len(selected_result)} instrument matches")
        
        mission_summary = f"{len(selected_missions)} mission(s): {', '.join(selected_missions)}"
        summary_info = [
            f"Systematic hierarchical search complete:",
            f"10 candidates → {mission_summary} → {len(filtered_catalog)} instruments → {len(selected_result)} matches",
            f"Matches: {', '.join([inst.instrument_code for inst in selected_result])}"
        ]
        logger.info('\n'.join(summary_info))
        
        # Apply post-validation filter to all results
        validated_results = self._validate_catalogue_entries(instrument_entry, selected_result)
        return validated_results if validated_results else None
    
    def _ground_instrument_parallel(self, instrument_entry: dict) -> Optional[List[CatalogueEntry]]:
        """
        Run grounding process in parallel across all available data systems.
        Merges results from all systems and returns combined results.
        """
        # Get all available data systems dynamically
        available_data_systems = self.finder.get_available_data_systems()
        
        if not available_data_systems:
            logger.warning("No data systems found in database")
            return None
        
        logger.info(f"Running parallel grounding across {len(available_data_systems)} data systems: {available_data_systems}")
        
        all_results = []
        system_contributions = {}
        
        # Run grounding for each data system
        for data_system in available_data_systems:
            logger.info(f"\n{'='*60}")
            logger.info(f"🔍 GROUNDING IN DATA SYSTEM: {data_system.upper()}")
            logger.info(f"{'='*60}")
            
            system_results = self._ground_instrument_for_data_system(instrument_entry, data_system)
            
            if system_results:
                # Add data system metadata to each result
                for result in system_results:
                    # Store the data system info for logging (don't modify the CatalogueEntry)
                    pass
                
                all_results.extend(system_results)
                system_contributions[data_system] = len(system_results)
                logger.info(f"✅ {data_system.upper()}: Found {len(system_results)} matches")
            else:
                system_contributions[data_system] = 0
                logger.info(f"❌ {data_system.upper()}: No matches found")
        
        # Log summary of contributions
        if all_results:
            total_results = len(all_results)
            logger.info(f"\n🎯 PARALLEL GROUNDING COMPLETE")
            logger.info(f"Total results: {total_results}")
            for system, count in system_contributions.items():
                if count > 0:
                    percentage = (count / total_results) * 100
                    logger.info(f"  {system.upper()}: {count} results ({percentage:.1f}%)")

            # If any specific instruments were found, suppress mission-only stubs.
            # Mission-only stubs are only useful when no specific instrument was resolved.
            specific = [r for r in all_results if r.instrument_code is not None]
            if specific:
                instrument_codes = [f"{r.instrument_code}/{r.mission_code}({r.data_system})" for r in specific]
                logger.info(f"Found instruments: {', '.join(instrument_codes)}")
                return specific

            # All results are mission-only — deduplicate by (mission_code, data_system)
            seen: set = set()
            deduped = []
            for r in all_results:
                key = (r.mission_code, r.data_system)
                if key not in seen:
                    seen.add(key)
                    deduped.append(r)
            mission_labels = [f"{r.mission_code}({r.data_system})" for r in deduped]
            logger.info(f"Mission-only stubs: {', '.join(mission_labels)}")
            return deduped
        else:
            logger.warning("No matches found across any data system")
            return None
    
    def _ground_instrument_for_data_system(self, instrument_entry: dict, data_system: str) -> Optional[List[CatalogueEntry]]:
        """
        Run the hierarchical grounding process for a specific data system.
        This is similar to _ground_instrument_hierarchical but uses data-system-specific methods.
        """
        with node_stage('grounding_datasystem', data_system) as ds_node:
            # Stage 1: Get candidate missions for this data system
            with node_stage('grounding_substep', 'mission_identification') as sn:
                candidate_mission_names = self._identify_missions_with_nano_for_data_system(instrument_entry, data_system, top_k=10)
                if sn is not None:
                    sn.metadata['missions'] = candidate_mission_names or []
                    sn.save(update_fields=['metadata'])

            if not candidate_mission_names:
                logger.warning(f"No candidate missions identified in {data_system} - too generic or unclear")
                return None

            # Stage 2: Select final mission(s) by index
            with node_stage('grounding_substep', 'mission_selection') as sn:
                selected_missions = self._select_final_mission(instrument_entry, candidate_mission_names)
                if sn is not None:
                    sn.metadata['missions'] = selected_missions or []
                    sn.save(update_fields=['metadata'])

            if not selected_missions:
                logger.warning(f"No final missions selected in {data_system} - description too ambiguous to disambiguate")
                return None

            # Stage 2.5: Validate selected mission(s)
            with node_stage('grounding_substep', 'mission_validation') as sn:
                validated_missions = self._validate_missions(instrument_entry, selected_missions, data_system)
                if sn is not None:
                    sn.metadata['results'] = [
                        {'mission': m, 'accepted': m in (validated_missions or [])}
                        for m in selected_missions
                    ]
                    sn.save(update_fields=['metadata'])

            if not validated_missions:
                logger.warning(f"No missions passed validation in {data_system}")
                return None

            selected_missions = validated_missions

            # Stage 3: Filter catalog by selected mission(s) within this data system
            filtered_catalog = self._filter_catalog_by_mission_names_for_data_system(selected_missions, data_system)

            if not filtered_catalog:
                mission_names_str = ', '.join(selected_missions)
                logger.warning(f"No instruments found in selected missions {mission_names_str} in {data_system}")
                # Mission was identified but has no instruments in this data system.
                # Try a cross-data-system lookup to get the canonical mission_code/name.
                all_ds_catalog = self._filter_catalog_by_mission_names(selected_missions)
                if all_ds_catalog:
                    ref = all_ds_catalog[0]
                    logger.info(f"Emitting mission-only entry for {ref.mission_code} in {data_system}")
                    return [CatalogueEntry(
                        instrument_code=None, instrument_name=None,
                        mission_code=ref.mission_code, mission_name=ref.mission_name,
                        data_system=data_system,
                    )]
                return None

            # Stage 4: Select ONE final instrument by index
            with node_stage('grounding_substep', 'instrument_selection') as sn:
                selected_result = self._select_final_instrument(instrument_entry, filtered_catalog)
                if sn is not None:
                    sn.metadata['instruments'] = [e.instrument_code for e in (selected_result or [])]
                    sn.save(update_fields=['metadata'])

            if not selected_result:
                logger.warning(f"No final instrument selected in {data_system} - multiple instruments could match equally")
                ref = filtered_catalog[0]
                logger.info(f"Emitting mission-only entry for {ref.mission_code} in {data_system} (instrument unresolvable)")
                return [CatalogueEntry(
                    instrument_code=None, instrument_name=None,
                    mission_code=ref.mission_code, mission_name=ref.mission_name,
                    data_system=data_system,
                )]

            logger.info(f"Found {len(selected_result)} instrument matches in {data_system}")

            mission_summary = f"{len(selected_missions)} mission(s): {', '.join(selected_missions)}"
            summary_info = [
                f"Data system {data_system} hierarchical search complete:",
                f"10 candidates → {mission_summary} → {len(filtered_catalog)} instruments → {len(selected_result)} matches",
                f"Matches: {', '.join([inst.instrument_code for inst in selected_result])}"
            ]
            logger.info('\n'.join(summary_info))

            # Apply post-validation filter to all results
            with node_stage('grounding_substep', 'instrument_validation') as sn:
                validated_results = self._validate_catalogue_entries(instrument_entry, selected_result)
                if sn is not None:
                    validated_codes = {e.instrument_code for e in (validated_results or [])}
                    sn.metadata['results'] = [
                        {'code': e.instrument_code, 'accepted': e.instrument_code in validated_codes}
                        for e in selected_result
                    ]
                    sn.save(update_fields=['metadata'])

            if not validated_results:
                ref = filtered_catalog[0]
                logger.info(f"Emitting mission-only entry for {ref.mission_code} in {data_system} (all candidates failed validation)")
                return [CatalogueEntry(
                    instrument_code=None, instrument_name=None,
                    mission_code=ref.mission_code, mission_name=ref.mission_name,
                    data_system=data_system,
                )]

            # Stamp each result with the data system node ID so the normalizer
            # can parent grounding_match nodes under this node
            if ds_node is not None:
                for entry in validated_results:
                    entry.pipeline_node_id = ds_node.id

            return validated_results

    def _validate_catalogue_entries(self, instrument_entry: dict, catalogue_entries: List[CatalogueEntry]) -> Optional[List[CatalogueEntry]]:
        """
        Validate CatalogueEntry objects and return only those that pass validation.
        Maintains the proper return type of Optional[List[CatalogueEntry]].
        """
        if not catalogue_entries:
            return None
            
        validated_entries = []
        for entry in catalogue_entries:
            if self._validate_single_catalogue_entry(instrument_entry, entry):
                validated_entries.append(entry)
            else:
                logger.info(f"Entry rejected by validation: {entry.instrument_code}/{entry.mission_code}")
                
        return validated_entries if validated_entries else None

    def _validate_single_catalogue_entry(self, instrument_entry: dict, catalogue_entry: CatalogueEntry) -> bool:
        """
        Validate a single CatalogueEntry using LLM validation.
        Returns True if valid, False if invalid.
        """
        logger.info("=== POST-VALIDATION FILTER ===")
        logger.info(f"Validating: {catalogue_entry.instrument_name} on {catalogue_entry.mission_name}")
        
        # Extract key information for validation
        original_name = instrument_entry.get("name", "")
        original_comments = instrument_entry.get("general_comments", "")

        # Build info from all data collection periods
        periods = instrument_entry.get("data_collection_periods", [])
        period_infos = []
        for period in periods:
            parts = []
            if period.get("time_range"):
                parts.append(f"Time period: {period['time_range']}")
            if period.get("physical_observable"):
                parts.append(f"Observes: {period['physical_observable']}")
            if period.get("wavelengths"):
                parts.append(f"Wavelengths: {period['wavelengths']}")
            if period.get("additional_comments"):
                parts.append(f"Comments: {period['additional_comments']}")
            if parts:
                period_infos.append("; ".join(parts))

        # Instrument description from registry
        matched_instrument_description = catalogue_entry.description or ""

        # Load validation prompt from XML template
        template_name = "validation"
        system_msg, user_msg = load_and_render_prompt(
            template_name,
            original_name=original_name,
            original_comments=original_comments,
            matched_instrument_name=catalogue_entry.instrument_name,
            matched_instrument_code=catalogue_entry.instrument_code,
            matched_instrument_description=matched_instrument_description,
            matched_mission_name=catalogue_entry.mission_name,
            matched_mission_code=catalogue_entry.mission_code,
            period_infos=period_infos,
        )

        # Capture template variables for render_context
        prompt_context = {
            'template_name': template_name,
            'original_name': original_name,
            'original_comments': original_comments,
            'matched_instrument_name': catalogue_entry.instrument_name,
            'matched_instrument_code': catalogue_entry.instrument_code,
            'matched_instrument_description': matched_instrument_description,
            'matched_mission_name': catalogue_entry.mission_name,
            'matched_mission_code': catalogue_entry.mission_code,
            'period_infos': period_infos,
        }

        try:
            # Use text-based validation (no structured output)
            config = self.llm_config.instrument_grounding.validation

            response = self.llm_client.completion(
                call_type="instrument_validation",
                model=config.model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                **config.to_kwargs(prompt_context=prompt_context)
            )

            raw_content = response.choices[0].message.content
            finish_reason = response.choices[0].finish_reason
            logger.info(f"Validation response (raw): {raw_content}")
            logger.info(f"Finish reason: {finish_reason}")
            
            # Parse the text response
            try:
                validation_result = self._parse_validation_response(raw_content)
                decision_bool = validation_result.get("decision") == "valid"

                logger.info(
                    f"Validation parsed decision: {validation_result.get('decision')} for {catalogue_entry.instrument_code}/{catalogue_entry.mission_code}"
                )

                # Trust the FINAL DECISION from the LLM
                return decision_bool
            except Exception as parse_err:
                logger.warning(
                    f"⚠️ Validation text parse failed; rejecting. Error: {parse_err}; excerpt: {str(raw_content)[:300]}"
                )
                return False
                
        except Exception as e:
            logger.error(f"Validation failed with error: {e}")
            logger.warning("Rejecting due to validation error (conservative default)")
            return False  # Conservative default on error

    def _parse_validation_response(self, raw_content: str) -> dict:
        """
        Parse text-based validation response into structured data.
        
        Expected format:
        VALIDATION ANALYSIS:
        - Name/Type alignment: [reasoning] → pass/fail
        - Mission reference match: [reasoning] → pass/fail
        - Temporal compatibility: [reasoning] → pass/fail
        - Scientific capability match: [reasoning] → pass/fail
        - Domain consistency: [reasoning] → pass/fail
        
        FINAL DECISION: valid/invalid
        """
        import re
        
        # Remove all asterisks from content to handle any markdown formatting variations
        clean_content = re.sub(r'\*+', '', raw_content)
        
        # Extract criteria results using cleaned content
        criteria_patterns = {
            "name_type": r"Name/Type alignment:.*?→\s*(pass|fail)",
            "mission_ref": r"Mission reference match:.*?→\s*(pass|fail)", 
            "temporal": r"Temporal compatibility:.*?→\s*(pass|fail)",
            "capability": r"Scientific capability match:.*?→\s*(pass|fail)",
            "domain": r"Domain consistency:.*?→\s*(pass|fail)"
        }
        
        criteria = {}
        for criterion_name, pattern in criteria_patterns.items():
            match = re.search(pattern, clean_content, re.IGNORECASE | re.DOTALL)
            if match:
                criteria[criterion_name] = match.group(1).lower()
            else:
                logger.warning(f"Could not find {criterion_name} result in validation response")
                criteria[criterion_name] = "fail"  # Conservative default
        
        # Extract final decision using cleaned content
        decision_pattern = r"FINAL\s+DECISION:\s*(valid|invalid)"
        decision_match = re.search(decision_pattern, clean_content, re.IGNORECASE)
        if decision_match:
            decision = decision_match.group(1).lower()
        else:
            logger.warning("Could not find FINAL DECISION in validation response")
            decision = "invalid"  # Conservative default
        
        return {
            "decision": decision,
            "criteria": criteria
        }

    def _validate_missions(self, instrument_entry: dict, selected_missions: List[str], data_system: str) -> Optional[List[str]]:
        """
        Validate selected mission(s) using LLM validation.
        Returns list of mission names that pass, or None if all fail.
        """
        if not selected_missions:
            return None

        # Look up Mission objects for code/description
        all_missions = self._get_unique_missions()
        mission_lookup = {}
        for m in all_missions:
            if m.data_system == data_system:
                mission_lookup[m.mission_name] = m

        validated = []
        for mission_name in selected_missions:
            mission_obj = mission_lookup.get(mission_name)
            if mission_obj is None:
                # Try cross-data-system lookup if not found in this data system
                for m in all_missions:
                    if m.mission_name == mission_name:
                        mission_obj = m
                        break
            if mission_obj is None:
                logger.warning(f"Mission '{mission_name}' not found in catalogue, skipping validation")
                validated.append(mission_name)  # Pass through if not found
                continue

            if self._validate_single_mission(instrument_entry, mission_obj):
                validated.append(mission_name)
            else:
                logger.info(f"Mission rejected by validation: {mission_name} in {data_system}")

        return validated if validated else None

    def _validate_single_mission(self, instrument_entry: dict, mission_obj: Mission) -> bool:
        """
        Validate a single mission using LLM validation.
        Returns True if valid, False if invalid.
        """
        logger.info("=== MISSION VALIDATION ===")
        logger.info(f"Validating mission: {mission_obj.mission_name} ({mission_obj.mission_code})")

        # Extract key information (same logic as _validate_single_catalogue_entry)
        original_name = instrument_entry.get("name", "")
        original_comments = instrument_entry.get("general_comments", "")

        periods = instrument_entry.get("data_collection_periods", [])
        period_infos = []
        for period in periods:
            parts = []
            if period.get("time_range"):
                parts.append(f"Time period: {period['time_range']}")
            if period.get("physical_observable"):
                parts.append(f"Observes: {period['physical_observable']}")
            if period.get("wavelengths"):
                parts.append(f"Wavelengths: {period['wavelengths']}")
            if period.get("additional_comments"):
                parts.append(f"Comments: {period['additional_comments']}")
            if parts:
                period_infos.append("; ".join(parts))

        matched_mission_description = mission_obj.description or ""

        template_name = "mission_validation"
        system_msg, user_msg = load_and_render_prompt(
            template_name,
            original_name=original_name,
            original_comments=original_comments,
            matched_mission_name=mission_obj.mission_name,
            matched_mission_code=mission_obj.mission_code,
            matched_mission_description=matched_mission_description,
            period_infos=period_infos,
        )

        prompt_context = {
            'template_name': template_name,
            'original_name': original_name,
            'original_comments': original_comments,
            'matched_mission_name': mission_obj.mission_name,
            'matched_mission_code': mission_obj.mission_code,
            'matched_mission_description': matched_mission_description,
            'period_infos': period_infos,
        }

        try:
            config = self.llm_config.instrument_grounding.mission_validation or self.llm_config.instrument_grounding.validation

            response = self.llm_client.completion(
                call_type="mission_validation",
                model=config.model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                **config.to_kwargs(prompt_context=prompt_context)
            )

            raw_content = response.choices[0].message.content
            finish_reason = response.choices[0].finish_reason
            logger.info(f"Mission validation response (raw): {raw_content}")
            logger.info(f"Finish reason: {finish_reason}")

            try:
                validation_result = self._parse_mission_validation_response(raw_content)
                decision_bool = validation_result.get("decision") == "valid"

                logger.info(
                    f"Mission validation parsed decision: {validation_result.get('decision')} for {mission_obj.mission_code}"
                )

                return decision_bool
            except Exception as parse_err:
                logger.warning(
                    f"Mission validation text parse failed; rejecting. Error: {parse_err}; excerpt: {str(raw_content)[:300]}"
                )
                return False

        except Exception as e:
            logger.error(f"Mission validation failed with error: {e}")
            logger.warning("Rejecting due to mission validation error (conservative default)")
            return False

    def _parse_mission_validation_response(self, raw_content: str) -> dict:
        """
        Parse text-based mission validation response into structured data.

        Expected format:
        VALIDATION ANALYSIS:
        - Domain alignment: [reasoning] → pass/fail
        - Temporal compatibility: [reasoning] → pass/fail
        - Explicit mention: [reasoning] → pass/fail
        - Scientific capability: [reasoning] → pass/fail

        FINAL DECISION: valid/invalid
        """
        import re

        # Remove all asterisks from content to handle any markdown formatting variations
        clean_content = re.sub(r'\*+', '', raw_content)

        criteria_patterns = {
            "domain_alignment": r"Domain alignment:.*?→\s*(pass|fail)",
            "temporal": r"Temporal compatibility:.*?→\s*(pass|fail)",
            "explicit_mention": r"Explicit mention:.*?→\s*(pass|fail)",
            "capability": r"Scientific capability:.*?→\s*(pass|fail)",
        }

        criteria = {}
        for criterion_name, pattern in criteria_patterns.items():
            match = re.search(pattern, clean_content, re.IGNORECASE | re.DOTALL)
            if match:
                criteria[criterion_name] = match.group(1).lower()
            else:
                logger.warning(f"Could not find {criterion_name} result in mission validation response")
                criteria[criterion_name] = "fail"  # Conservative default

        decision_pattern = r"FINAL\s+DECISION:\s*(valid|invalid)"
        decision_match = re.search(decision_pattern, clean_content, re.IGNORECASE)
        if decision_match:
            decision = decision_match.group(1).lower()
        else:
            logger.warning("Could not find FINAL DECISION in mission validation response")
            decision = "invalid"  # Conservative default

        return {
            "decision": decision,
            "criteria": criteria
        }
