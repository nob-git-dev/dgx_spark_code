import json
from collections.abc import Sequence
from random import choices
from string import ascii_letters, digits
from typing import Optional, Union, Any

import partial_json_parser
import regex as re
from partial_json_parser.core.options import Allow
from pydantic import Field

from vllm.entrypoints.openai.protocol import (ChatCompletionRequest,
                                              DeltaFunctionCall, DeltaMessage,
                                              DeltaToolCall,
                                              ExtractedToolCallInformation,
                                              FunctionCall, ToolCall)
from vllm.logger import init_logger

try:
    from vllm.tool_parsers import ToolParser, ToolParserManager
except ImportError:
    from vllm.entrypoints.openai.tool_parsers import ToolParser, ToolParserManager

try:
    from vllm.tokenizers import TokenizerLike
except ImportError:
    from vllm.transformers_utils.tokenizer import AnyTokenizer as TokenizerLike


logger = init_logger(__name__)

ALPHANUMERIC = ascii_letters + digits

# Common exception types for JSON parsing attempts
JSON_PARSE_EXCEPTIONS = (
    partial_json_parser.MalformedJSON,
    json.JSONDecodeError,
    ValueError,
    AssertionError,
)


class NemotronToolCall(ToolCall):
    id: str = Field(
        default_factory=lambda: NemotronToolCall.generate_random_id())

    @staticmethod
    def generate_random_id():
        return "".join(choices(ALPHANUMERIC, k=9))

    @staticmethod
    def is_valid_id(id: str) -> bool:
        return id.isalnum() and len(id) == 9


@ToolParserManager.register_module("nemotron_json")
class NemotronToolParser(ToolParser):
    """
    Tool call parser for Nemotron-Nano-V2

    Used when --enable-auto-tool-choice --tool-call-parser nemotron_json are all set
    """

    def __init__(self, tokenizer: TokenizerLike):
        super().__init__(tokenizer)
        # initialize properties used for state when parsing tool calls in streaming mode
        self.prev_tool_call_arr: list[dict] = []
        self.current_tool_id: int = -1
        self.current_tool_name_sent: bool = False
        # map what has been streamed for each tool so far to a list
        self.streamed_args_for_tool: list[str] = []
        self.tool_args_emitted: list[bool] = []
        self.bot_token = "<TOOLCALL>"
        self.eot_token = "</TOOLCALL>"
        # regex patterns for non-streaming parsing
        self.tool_calls_regex = re.compile(r"<TOOLCALL>(.*?)</TOOLCALL>", re.DOTALL)
        self.tool_call_regex = re.compile(r'(^\[|, ?)({"name": ?"[^"]*", ?"arguments":)', re.DOTALL)
        # Buffer for partial tag sequences to disambiguate between normal content and
        # a forthcoming <TOOLCALL> or </TOOLCALL> tag in streaming.
        self._pending_tag_buffer: str = ""
        # Track tool calls already parsed in fallback mode (by name and position)
        # to avoid re-parsing the same tool calls multiple times during streaming
        self._fallback_parsed_tools: list[tuple[str, int]] = []  # List of (name, start_pos) tuples
        # Track the number of tool calls that were successfully parsed by standard parser
        # to skip re-parsing them in fallback mode
        self._last_standard_parse_count: int = 0

    @staticmethod
    def _strip_trailing_auto_closers(chunk: str) -> str:
        """
        Remove parser auto-completed closing braces/brackets plus trailing whitespace.
        These should be flushed only when a tool call completes to avoid duplicate
        argument fragments.
        """
        idx = len(chunk)
        while idx > 0 and chunk[idx - 1] in " \t\r\n}]":
            idx -= 1
        # Remove trailing non-escaped double quotes (partial JSON auto-closes strings)
        while idx > 0 and chunk[idx - 1] == '"':
            # keep escaped quotes (\"), only strip bare ones
            if idx - 2 >= 0 and chunk[idx - 2] == '\\':
                break
            idx -= 1
        return chunk[:idx]

    @staticmethod
    def _common_prefix_len(left: str, right: str) -> int:
        """
        Return the length of the shared prefix between left and right strings.
        """
        max_len = min(len(left), len(right))
        idx = 0
        while idx < max_len and left[idx] == right[idx]:
            idx += 1
        return idx

    @staticmethod
    def _skip_whitespace_and_comma(content: str, pos: int) -> int:
        """Skip comma and whitespace characters, return new position."""
        while pos < len(content) and content[pos] in ', \t\r\n':
            pos += 1
        return pos

    @staticmethod
    def _skip_json_object(content: str, start_pos: int) -> int:
        """
        Skip past a JSON object by counting braces while respecting strings.
        Assumes start_pos is positioned just after the opening '{'.
        Returns position after the closing '}' (or end of content if unmatched).
        """
        pos = start_pos
        depth = 1
        while pos < len(content) and depth > 0:
            ch = content[pos]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
            elif ch == '"':
                # Skip string content (handles escaped characters)
                pos += 1
                while pos < len(content):
                    if content[pos] == '\\' and pos + 1 < len(content):
                        pos += 2
                        continue
                    if content[pos] == '"':
                        break
                    pos += 1
            pos += 1
        return pos

    @staticmethod
    def _get_param_config(request: ChatCompletionRequest) -> dict[str, dict[str, str]]:
        tool_param_config = {}
        if not request.tools:
            return tool_param_config

        for tool in request.tools:
            if not (hasattr(tool, "function") or hasattr(tool.function, "parameters")):
                continue

            param_config = {}
            for param_name, param_type in tool.function.parameters.items():
                if isinstance(param_type, dict) and "type" in param_type:
                    param_config[param_name] = param_type["type"]
            tool_param_config[tool.function.name] = param_config

        return tool_param_config

    @staticmethod
    def _convert_param_value(value: Union[str, Any], param_type: str) -> Any:
        """Convert parameter value to the correct type."""
        param_type = param_type.lower()

        if param_type in ["string", "str", "text"]:
            try:
                if isinstance(value, str):
                    return value
                elif isinstance(value, dict) or isinstance(value, list):
                    return json.dumps(value, ensure_ascii=False)
                elif value is not None:
                    return str(value)
                else:
                    return value
            except:
                return value

        if isinstance(value, str) and value.lower() == "null":
            return None

        if param_type in ["integer", "int"]:
            try:
                return int(value)
            except (ValueError, TypeError):
                return value
        elif param_type in ["number", "float"]:
            try:
                val = float(value)
                return val if val != int(val) else int(val)
            except (ValueError, TypeError):
                return value
        elif isinstance(value, str) and param_type in ["boolean", "bool"]:
            return value.lower() in ["true", "1"]
        elif isinstance(value, str) and param_type in ["object", "array"]:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        else:
            # Try JSON parse first, fallback to string
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value

    def _compute_arguments_delta(self, cur_arguments_json: str,
                                 end_of_call: bool) -> str:
        """
        Determine the incremental suffix to stream for the current tool call.
        Ensures we only emit monotonic chunks by trimming our tracked prefix to
        the longest common prefix with the latest JSON snapshot.
        """
        tool_idx = self.current_tool_id
        if tool_idx < 0 or tool_idx >= len(self.streamed_args_for_tool):
            return ""

        streamed_prefix = self.streamed_args_for_tool[tool_idx]
        had_any = (self.tool_args_emitted[tool_idx]
                   if tool_idx < len(self.tool_args_emitted) else False)

        lcp_len = self._common_prefix_len(cur_arguments_json,
                                          streamed_prefix)
        if lcp_len != len(streamed_prefix):
            streamed_prefix = streamed_prefix[:lcp_len]
            self.streamed_args_for_tool[tool_idx] = streamed_prefix

        if (not had_any and not end_of_call and lcp_len == 0
                and cur_arguments_json.endswith('": ""}')
                and '": ""' in cur_arguments_json):
            closing_pos = cur_arguments_json.rfind('": ""}')
            if closing_pos != -1:
                arguments_delta = cur_arguments_json[:closing_pos + 4]
            else:
                arguments_delta = cur_arguments_json
        else:
            arguments_delta = cur_arguments_json[lcp_len:]

        if not arguments_delta:
            return ""

        if not end_of_call:
            arguments_delta = self._strip_trailing_auto_closers(
                arguments_delta)

        if (not had_any and not end_of_call and arguments_delta
                and arguments_delta.endswith('}')):
            arguments_delta = arguments_delta[:-1]
            if arguments_delta.endswith('"'):
                arguments_delta = arguments_delta[:-1]

        return arguments_delta

    def _visible_delta_outside_tool(self, delta_text: str,
                                    start_token: Optional[str],
                                    end_token: Optional[str]) -> str:
        """
        Consume characters that could begin a tool tag. Only suppress the exact
        <TOOLCALL> / </TOOLCALL> sequences, and let everything else (e.g. </think>)
        pass through untouched.
        """
        if not delta_text:
            return delta_text

        visible: list[str] = []
        for ch in delta_text:
            if self._pending_tag_buffer or ch == '<':
                self._pending_tag_buffer += ch

                if start_token and start_token.startswith(self._pending_tag_buffer):
                    if self._pending_tag_buffer == start_token:
                        self._pending_tag_buffer = ""
                    continue

                if end_token and end_token.startswith(self._pending_tag_buffer):
                    if self._pending_tag_buffer == end_token:
                        self._pending_tag_buffer = ""
                    continue

                # Not a tool tag; flush buffered characters as normal content.
                visible.append(self._pending_tag_buffer)
                self._pending_tag_buffer = ""
            else:
                visible.append(ch)

        return "".join(visible)

    def adjust_request(self, request: ChatCompletionRequest) -> ChatCompletionRequest:
        if request.tools and request.tool_choice != 'none':
            # Do not skip special tokens when using chat template
            # with Mistral parser as TOOL_CALL token is needed
            # for tool detection.
            request.skip_special_tokens = False
        return request

    def _parse_tool_calls_fallback(self, parsable_arr: str) -> list[dict]:
        """
        Fall back to incremental parsing with state tracking.
        Tool calls must follow: {"name": "...", "arguments": {...}}
        - Parse incrementally from each '{'
        - Confirm "name" key appears first
        - Then confirm "arguments" key appears second
        - If state transitions are violated, skip to next '{'
        - When parse fails (malformed JSON), use last successful parse as one tool call
        """
        tool_call_arr: list[dict] = []
        content = parsable_arr.strip()
        if content.startswith('['):
            content = content[1:]
        if content.endswith(']'):
            content = content[:-1]
        content = content.strip()

        if not content:
            return tool_call_arr

        current_pos = 0

        # Optimization: If standard parser previously succeeded with N tool calls,
        # use prev_tool_call_arr for those and skip to the (N+1)-th tool call position
        if self._last_standard_parse_count > 0 and len(self.prev_tool_call_arr) >= self._last_standard_parse_count:
            # Copy tool calls from previous successful parse
            tool_call_arr = list(self.prev_tool_call_arr[:self._last_standard_parse_count])
            # Skip past the first N '{' positions to find where to start incremental parsing
            skipped = 0
            while current_pos < len(content) and skipped < self._last_standard_parse_count:
                brace_pos = content.find('{', current_pos)
                if brace_pos == -1:
                    break
                # Track this position as already parsed
                if not any(pos == brace_pos for _, pos in self._fallback_parsed_tools):
                    tool_name = tool_call_arr[skipped].get('name', '') if skipped < len(tool_call_arr) else ''
                    self._fallback_parsed_tools.append((tool_name, brace_pos))
                skipped += 1
                current_pos = self._skip_json_object(content, brace_pos + 1)
                current_pos = self._skip_whitespace_and_comma(content, current_pos)

        while current_pos < len(content):
            # Find next '{' from current position
            brace_pos = content.find('{', current_pos)
            if brace_pos == -1:
                break

            # Check if this position was already parsed in a previous streaming call
            if any(pos == brace_pos for _, pos in self._fallback_parsed_tools):
                current_pos = brace_pos + 1
                continue

            remaining = content[brace_pos:]
            parsed_result = self._try_incremental_tool_parse(remaining)

            if parsed_result is None:
                # Not a valid tool call start, skip to next '{'
                current_pos = brace_pos + 1
                continue

            tool_call, end_pos = parsed_result
            if tool_call:
                tool_call_arr.append(tool_call)
                tool_name = tool_call.get('name', '')
                self._fallback_parsed_tools.append((tool_name, brace_pos))
                current_pos = brace_pos + end_pos
                current_pos = self._skip_whitespace_and_comma(content, current_pos)
            else:
                # No valid tool call found from this '{', try next
                current_pos = brace_pos + 1

        return tool_call_arr

    def _try_incremental_tool_parse(self, json_str: str) -> Optional[tuple[Optional[dict], int]]:
        """
        Attempt to incrementally parse a tool call from JSON string.
        Returns:
          - (parsed_dict, end_pos) if a valid tool call was found
          - (None, 0) if no valid tool call found but should continue
          - None if the JSON structure doesn't look like a tool call (skip to next '{')
        """
        last_valid_parse = None
        last_valid_end = 0

        for end_pos in range(1, len(json_str) + 1):
            test_json = json_str[:end_pos]
            try:
                parsed = partial_json_parser.loads(test_json, Allow.ALL)
                if parsed and isinstance(parsed, dict):
                    keys = list(parsed.keys())

                    if len(keys) == 0:
                        # Empty object, continue
                        continue

                    # First key must be 'name'
                    if keys[0] != 'name':
                        # Not a valid tool call start
                        return None

                    # If there are more keys, second must be 'arguments'
                    if len(keys) > 1 and keys[1] != 'arguments':
                        # Not a valid tool call
                        return None

                    # Valid state - track if we have both name and arguments
                    if 'name' in parsed and 'arguments' in parsed:
                        last_valid_parse = parsed
                        last_valid_end = end_pos

            except JSON_PARSE_EXCEPTIONS:
                # Parse failed - if we have a valid parse with both keys, use it
                if last_valid_parse:
                    break
                # Otherwise continue trying (might be incomplete JSON that becomes valid)
                continue

        return (last_valid_parse, last_valid_end)

    def _try_single_tool_call_parse(self, str_tool_call: str) -> dict:
        fix_brace = lambda s: s + '}'
        fix_quote = lambda s: s.replace(r'\""', '"').replace(r'"\"', '"').replace(r"\'", "'")
        for fixed_str_tool_call in [
            str_tool_call,
            fix_brace(str_tool_call),
            fix_quote(str_tool_call),
            fix_brace(fix_quote(str_tool_call)),
        ]:
            try:
                return json.loads(fixed_str_tool_call)
            except json.JSONDecodeError:
                continue
        return None

    def extract_tool_calls(
        self,
        model_output: str,
        request: ChatCompletionRequest,
    ) -> ExtractedToolCallInformation:
        """
        Extract the tool calls from a complete model response. Requires
        find-and-replacing single quotes with double quotes for JSON parsing,
        make sure your tool call arguments don't ever include quotes!
        """

        # case -- if a tool call token is not present, return a text response
        if self.bot_token not in model_output:
            return ExtractedToolCallInformation(tools_called=False,
                                                tool_calls=[],
                                                content=model_output)

        try:
            str_tool_calls = self.tool_calls_regex.findall(model_output)[0].strip()
            if not str_tool_calls.startswith("["):
                str_tool_calls = "[" + str_tool_calls
            if not str_tool_calls.endswith("]"):
                str_tool_calls = "]" + str_tool_calls
            try:
                function_call_arr = json.loads(str_tool_calls)
            except json.JSONDecodeError:
                logger.warning(f"Error in parsing tool call: {str_tool_calls}")
                tool_call_prefix_matches = list(self.tool_call_regex.finditer(str_tool_calls))
                for i, match in enumerate(tool_call_prefix_matches):
                    if i == len(tool_call_prefix_matches) - 1:
                        str_tool_call = str_tool_calls[match.start():]
                    else:
                        str_tool_call = str_tool_calls[match.start():tool_call_prefix_matches[i+1].start()]

                    str_tool_call = str_tool_call[str_tool_call.find("{"):]
                    tool_call = self._try_single_tool_call_parse(str_tool_call)
                    if tool_call is not None:
                        function_call_arr.append(tool_call)
                        continue

            # Get parameter configuration for type conversion
            tool_param_config = self._get_param_config(request)

            for function_call in function_call_arr:
                fn_name = function_call["name"]
                args = function_call["arguments"]
                if isinstance(args, str):
                    args = json.loads(args)

                for param_name in list(args.keys()):
                    # Get parameter type
                    param_type = tool_param_config.get(fn_name, {}).get(param_name, None)
                    # Convert param value to appropriate type
                    if param_type is not None:
                        args[param_name] = self._convert_param_value(args[param_name], param_type)

            # Tool Call
            tool_calls: list[NemotronToolCall] = [
                NemotronToolCall(
                    type="function",
                    function=FunctionCall(
                        name=raw_function_call["name"],
                        # function call args are JSON but as a string
                        arguments=json.dumps(raw_function_call["arguments"], ensure_ascii=False)
                    )
                ) for raw_function_call in function_call_arr
            ]

            # get any content before  the tool call
            content = model_output.split(self.bot_token)[0]
            return ExtractedToolCallInformation(
                tools_called=True,
                tool_calls=tool_calls,
                content=content if len(content) > 0 else None)

        except Exception:
            logger.warning(f"Error in extracting tool call from response: {model_output}")
            # return information to just treat the tool call as regular JSON
            return ExtractedToolCallInformation(tools_called=False,
                                                tool_calls=[],
                                                content=model_output)

    def extract_tool_calls_streaming(
        self,
        previous_text: str,
        current_text: str,
        delta_text: str,
        previous_token_ids: Sequence[int],
        current_token_ids: Sequence[int],
        delta_token_ids: Sequence[int],
        request: ChatCompletionRequest,
    ) -> Union[DeltaMessage, None]:
        # if candidates tool call tokens are in the tokens generated so far, that
        # means we're parsing as tool calls now. Suppress streaming if we are
        # currently generating any prefix of the start or end tag.
        visible_delta_text = delta_text
        try:
            visible_delta_text = self._visible_delta_outside_tool(delta_text, self.bot_token, self.eot_token)
        except Exception:
            # Fallback to conservative checks in case of any issues
            if current_text.endswith('<') or current_text.endswith('<T') or current_text.endswith('<TO') or current_text.endswith('<TOOL') or current_text.endswith('<TOOLCALL'):
                return None

        # if the tool call token is not in the tokens generated so far, append
        # output to contents since it's not a tool
        if self.bot_token not in current_text:
            if visible_delta_text:
                return DeltaMessage(content=visible_delta_text)
            # still waiting on a potential tag, so emit nothing yet
            return None

        # bit mask flags for partial JSON parsing. If the name hasn't been
        # sent yet, don't allow sending
        # an incomplete string since OpenAI only ever (as far as I have
        # seen) allows sending the entire tool/ function name at once.
        # flags = Allow.ALL if self.current_tool_name_sent else (Allow.ALL & ~Allow.STR)
        # flags = Allow.ALL & ~Allow.STR
        flags = Allow.ALL & ~Allow.ATOM
        end_of_call: bool = False
        try:
            # replace BOT token with empty string, and convert single quotes
            # to double to allow parsing as JSON since mistral uses single
            # quotes instead of double for tool calls
            parsable_arr = current_text.split(self.bot_token)[-1]
            
            # Check if we're at the end of the tool call
            if '</TOOLCALL>' in parsable_arr:
                end_of_call = True
                parsable_arr = parsable_arr.split('</TOOLCALL>')[0]
                # Reset fallback state for next tool call array
                self._fallback_parsed_tools = []
                self._last_standard_parse_count = 0

            # tool calls are generated in an array, so do partial JSON
            # parsing on the entire array
            tool_call_arr: list[dict] = []
            try:
                tool_call_arr = partial_json_parser.loads(parsable_arr, flags)
                # Track the number of successfully parsed tool calls
                if isinstance(tool_call_arr, list):
                    self._last_standard_parse_count = len(tool_call_arr)
            except JSON_PARSE_EXCEPTIONS:
                tool_call_arr = self._parse_tool_calls_fallback(parsable_arr)

            if len(tool_call_arr) == 0:
                return None

            current_tool_call: dict = tool_call_arr[self.current_tool_id] \
                if len(tool_call_arr) > 0 and self.current_tool_id < len(tool_call_arr) else {}

            # case: we are starting a new tool in the array
            #   -> array has > 0 length AND length has moved past cursor
            if (len(tool_call_arr) > 0 and len(tool_call_arr) > self.current_tool_id + 1):

                # if we're moving on to a new call, first make sure we
                # haven't missed anything in the previous one that was
                # auto-generated due to JSON completions, but wasn't
                # streamed to the client yet.
                if self.current_tool_id >= 0:
                    diff: Union[str, None] = current_tool_call.get("arguments")

                    if diff:
                        diff = json.dumps(diff, ensure_ascii=False).replace(
                            self.streamed_args_for_tool[self.current_tool_id], "")
                        if not diff:
                            return None
                        delta = DeltaMessage(tool_calls=[
                            DeltaToolCall(
                                index=self.current_tool_id,
                                function=DeltaFunctionCall(arguments=diff).model_dump(exclude_none=True)
                            )
                        ])
                        self.streamed_args_for_tool[self.current_tool_id] += diff
                    else:
                        delta = None
                else:
                    delta = None
                # re-set stuff pertaining to progress in the current tool
                self.current_tool_id = len(tool_call_arr) - 1
                self.current_tool_name_sent = False
                self.streamed_args_for_tool.append("")
                self.tool_args_emitted.append(False)
                return delta

            # case: update an existing tool - this is handled below

            # if the current tool name hasn't been sent, send if available
            # - otherwise send nothing
            if not self.current_tool_name_sent:
                function_name = current_tool_call.get("name")
                if function_name:

                    delta = DeltaMessage(tool_calls=[
                        DeltaToolCall(
                            index=self.current_tool_id,
                            type="function",
                            id=NemotronToolCall.generate_random_id(),
                            function=DeltaFunctionCall(name=function_name).model_dump(exclude_none=True)
                        )
                    ])
                    self.current_tool_name_sent = True
                else:
                    delta = None

            # now we know we're on the same tool call and we're streaming
            # arguments
            else:
                prev_arguments = self.prev_tool_call_arr[self.current_tool_id].get("arguments")
                cur_arguments = current_tool_call.get("arguments")

                if not cur_arguments and not prev_arguments:
                    delta = None
                elif not cur_arguments and prev_arguments:
                    logger.error("INVARIANT - impossible to have arguments reset mid-arguments")
                    delta = None
                elif cur_arguments:
                    cur_arguments_json = json.dumps(cur_arguments, ensure_ascii=False)
                    arguments_delta = self._compute_arguments_delta(cur_arguments_json, end_of_call)
                    if arguments_delta:
                        delta = DeltaMessage(tool_calls=[
                            DeltaToolCall(
                                index=self.current_tool_id,
                                function=DeltaFunctionCall(arguments=arguments_delta).model_dump(exclude_none=True)
                            )
                        ])
                        self.streamed_args_for_tool[self.current_tool_id] += arguments_delta
                        self.tool_args_emitted[self.current_tool_id] = True
                    else:
                        # Do not flush final JSON here; let the serving layer
                        # compute a minimal remaining suffix on finish.
                        delta = None
                else:
                    # End-of-call or equal state; do not force a final flush here.
                    delta = None

            # check to see if the name is defined and has been sent. if so,
            # stream the name - otherwise keep waiting
            # finish by setting old and returning None as base case
            self.prev_tool_call_arr = tool_call_arr
            # If we've reached the end of a tool call, flush any remaining
            # suffix (including a final '}') that hasn't been streamed yet.
            if end_of_call and self.current_tool_id >= 0:
                try:
                    cur_arguments = current_tool_call.get("arguments")
                    if cur_arguments is not None:
                        cur_args_json = json.dumps(cur_arguments, ensure_ascii=False)
                        remaining_suffix = self._compute_arguments_delta(cur_args_json, end_of_call=True)

                        # Only send remaining suffix if it's non-empty and contains meaningful content
                        # (not just whitespace or single characters like closing braces)
                        if remaining_suffix and remaining_suffix.strip():
                            extra = DeltaToolCall(
                                index=self.current_tool_id,
                                function=DeltaFunctionCall(arguments=remaining_suffix).model_dump(exclude_none=True)
                            )
                            if delta is None:
                                delta = DeltaMessage(tool_calls=[extra])
                            else:
                                if getattr(delta, "tool_calls", None):
                                    delta.tool_calls.append(extra)
                                else:
                                    delta.tool_calls = [extra]
                            self.streamed_args_for_tool[self.current_tool_id] += remaining_suffix
                            self.tool_args_emitted[self.current_tool_id] = True
                        else:
                            pass
                except Exception:
                    pass

            return delta

        except Exception:
            logger.exception("Error trying to handle streaming tool call.")
            return None
