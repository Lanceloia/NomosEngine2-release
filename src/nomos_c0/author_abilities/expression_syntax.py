"""Closed expression grammar with token positions, never executable Python AST."""

from __future__ import annotations

import ast
import io
import keyword
import re
import tokenize
from dataclasses import dataclass, replace

from nomos_c0.author_contract_v1 import C0LawError
from nomos_c0.author_document_v1 import C0SourceSpan


@dataclass(frozen=True)
class ExpressionLimits:
    bytes: int = 65536
    tokens: int = 8192
    nodes: int = 32768
    depth: int = 64
    steps: int = 100000

    def __post_init__(self):
        if any(type(value) is not int or value < 1 for value in vars(self).values()):
            raise C0LawError("expression budgets must be positive integers")


@dataclass(frozen=True)
class ExpressionDiagnostic:
    code: str
    stage: str
    path: str
    offset: int
    line: int
    column: int
    span: C0SourceSpan | None
    expected: str
    actual: str


class ExpressionError(C0LawError):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        source = diagnostic.span.file if diagnostic.span is not None else diagnostic.path
        super().__init__(
            f"{diagnostic.code}: {source}:{diagnostic.line}:{diagnostic.column}: "
            f"{diagnostic.expected}; {diagnostic.actual}"
        )


@dataclass(frozen=True)
class ExpressionSource:
    text: str
    path: str = "expression"
    span: C0SourceSpan | None = None

    def fail(self, code, offset, expected, actual, *, stage="Compile"):
        prefix = self.text[:offset]
        line = prefix.count("\n") + 1
        column = len(prefix.rsplit("\n", 1)[-1]) + 1
        if self.span is not None:
            column += self.span.column - 1 if line == 1 else 0
            line += self.span.line - 1
        raise ExpressionError(
            ExpressionDiagnostic(
                code, stage, self.path, offset, line, column, self.span, expected, actual
            )
        )


@dataclass(frozen=True)
class Syntax:
    operation: str
    value: object = None
    children: tuple[Syntax, ...] = ()
    start: int = 0
    end: int = 0


@dataclass(frozen=True)
class _Token:
    text: str
    kind: int
    start: int
    end: int


def _identifier(text):
    return (
        type(text) is str
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", text) is not None
        and not keyword.iskeyword(text)
    )


def _tokens(source, limits):
    if (
        type(source.text) is not str
        or len(source.text.encode("utf-8", errors="surrogatepass")) > limits.bytes
    ):
        source.fail("ExpressionBudget", 0, "bounded expression text", "byte limit")
    lines = source.text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    def position(pair):
        row, column = pair
        return offsets[min(row - 1, len(offsets) - 1)] + column

    result = []
    try:
        stream = tokenize.generate_tokens(io.StringIO(source.text).readline)
        for token in stream:
            if token.type in (tokenize.NL, tokenize.NEWLINE, tokenize.ENDMARKER):
                continue
            if token.type not in (tokenize.NAME, tokenize.NUMBER, tokenize.STRING, tokenize.OP):
                source.fail(
                    "InvalidSyntax", position(token.start), "expression token", token.string
                )
            result.append(
                _Token(token.string, token.type, position(token.start), position(token.end))
            )
            if len(result) > limits.tokens:
                source.fail(
                    "ExpressionBudget", position(token.start), "bounded token count", "token limit"
                )
    except (tokenize.TokenError, IndentationError, SyntaxError) as error:
        source.fail("InvalidSyntax", len(source.text), "complete expression", type(error).__name__)
    result.append(_Token("<end>", tokenize.ENDMARKER, len(source.text), len(source.text)))
    return result


class _Parser:
    def __init__(self, source, limits):
        self.source, self.limits = source, limits
        self.tokens = _tokens(source, limits)
        self.index = self.nodes = self.depth = 0

    @property
    def current(self):
        return self.tokens[self.index]

    def take(self, text=None):
        token = self.current
        if text is not None and token.text != text:
            self.source.fail("InvalidSyntax", token.start, text, token.text)
        self.index += 1
        return token

    def accept(self, text):
        if self.current.text != text:
            return False
        self.take()
        return True

    def node(self, operation, value=None, children=(), start=None, end=None):
        self.nodes += 1
        if self.nodes > self.limits.nodes:
            self.source.fail(
                "ExpressionBudget", self.current.start, "bounded syntax nodes", "node limit"
            )
        return Syntax(
            operation,
            value,
            tuple(children),
            self.current.start if start is None else start,
            self.current.start if end is None else end,
        )

    def expression(self):
        self.depth += 1
        if self.depth > self.limits.depth:
            self.source.fail(
                "ExpressionBudget", self.current.start, "bounded nesting", "depth limit"
            )
        value = self.binary(0)
        if self.accept("if"):
            condition = self.binary(0)
            self.take("else")
            other = self.expression()
            value = self.node(
                "if", children=(condition, value, other), start=value.start, end=other.end
            )
        self.depth -= 1
        return value

    def binary(self, level):
        if level == 2 and self.accept("not"):
            start = self.tokens[self.index - 1].start
            self.depth += 1
            if self.depth > self.limits.depth:
                self.source.fail("ExpressionBudget", start, "bounded not nesting", "depth limit")
            child = self.binary(level)
            self.depth -= 1
            return self.node("not", children=(child,), start=start, end=child.end)
        if level == 5:
            if self.current.text in ("+", "-"):
                token = self.take()
                self.depth += 1
                if self.depth > self.limits.depth:
                    self.source.fail(
                        "ExpressionBudget", token.start, "bounded unary nesting", "depth limit"
                    )
                child = self.binary(level)
                self.depth -= 1
                return self.node("unary", token.text, (child,), token.start, child.end)
            return self.postfix()
        operators = (
            ("or",),
            ("and",),
            ("==", "!=", "<", "<=", ">", ">=", "in", "is", "not"),
            ("+", "-"),
            ("*", "//", "%"),
        )[level]
        value = self.binary(level + 1)
        seen = False
        while self.current.text in operators:
            if level == 2 and seen:
                self.source.fail(
                    "InvalidSyntax", self.current.start, "one comparison", "chained comparison"
                )
            token = self.take()
            operation = token.text
            if level == 2 and operation == "not":
                self.take("in")
                operation = "not in"
            elif level == 2 and operation == "is" and self.accept("not"):
                operation = "is not"
            child = self.binary(level + 1)
            value = self.node("binary", operation, (value, child), value.start, child.end)
            seen = True
        return value

    def postfix(self):
        token = self.take()
        if token.text == "match":
            value = self.match(token)
        elif token.text == "(":
            value = self.expression()
            end = self.take(")")
            value = replace(value, start=token.start, end=end.end)
        elif token.text == "[":
            values = []
            if self.current.text != "]":
                while True:
                    values.append(self.expression())
                    if not self.accept(",") or self.current.text == "]":
                        break
            end = self.take("]")
            value = self.node("list", children=values, start=token.start, end=end.end)
        elif token.text in ("True", "False", "None"):
            value = self.node(
                "literal",
                {"True": True, "False": False, "None": None}[token.text],
                start=token.start,
                end=token.end,
            )
        elif token.kind == tokenize.NUMBER and re.fullmatch(r"[0-9]+", token.text):
            try:
                number = int(token.text)
            except ValueError:
                self.source.fail(
                    "ExpressionBudget", token.start, "bounded integer literal", "digit limit"
                )
            value = self.node("literal", number, start=token.start, end=token.end)
        elif token.kind == tokenize.STRING and token.text[0] in "\"'":
            try:
                string = ast.literal_eval(token.text)
            except (ValueError, SyntaxError):
                self.source.fail("InvalidSyntax", token.start, "text literal", "invalid escaping")
            value = self.node("literal", string, start=token.start, end=token.end)
        elif token.kind == tokenize.NAME and _identifier(token.text):
            value = self.node("name", token.text, start=token.start, end=token.end)
        else:
            self.source.fail(
                "InvalidSyntax", token.start, "literal, name or grouped expression", token.text
            )
        while self.current.text in (".", "("):
            if self.accept("."):
                field = self.take()
                if not _identifier(field.text):
                    self.source.fail(
                        "InvalidSyntax", field.start, "declared field name", field.text
                    )
                value = self.node("field", field.text, (value,), value.start, field.end)
                continue
            self.take("(")
            arguments = []
            if self.current.text != ")":
                while True:
                    name = self.current
                    following = self.tokens[self.index + 1]
                    if (
                        name.kind == tokenize.NAME
                        and _identifier(name.text)
                        and following.text == "="
                    ):
                        self.take()
                        self.take("=")
                        if self.accept(">"):
                            if self.tokens[self.index - 1].start != following.end:
                                self.source.fail(
                                    "InvalidSyntax", following.start, "=>", "separated arrow"
                                )
                            body = self.expression()
                            argument = self.node("lambda", name.text, (body,), name.start, body.end)
                        else:
                            body = self.expression()
                            argument = self.node(
                                "keyword", name.text, (body,), name.start, body.end
                            )
                    else:
                        argument = self.expression()
                    arguments.append(argument)
                    if not self.accept(",") or self.current.text == ")":
                        break
            end = self.take(")")
            value = self.node("call", children=(value, *arguments), start=value.start, end=end.end)
        return value

    def match(self, token):
        self.take("(")
        subject = self.expression()
        self.take(",")
        cases = []
        while self.current.text != ")":
            tag = self.take()
            if not _identifier(tag.text):
                self.source.fail("InvalidSyntax", tag.start, "Variant case label", tag.text)
            self.take("(")
            binder = None
            if self.current.text != ")":
                name = self.take()
                if not _identifier(name.text):
                    self.source.fail("InvalidSyntax", name.start, "case binding name", name.text)
                binder = name.text
            self.take(")")
            arrow = self.take("=")
            end_arrow = self.take(">")
            if arrow.end != end_arrow.start:
                self.source.fail("InvalidSyntax", arrow.start, "=>", "separated arrow")
            body = self.expression()
            cases.append(self.node("case", (tag.text, binder), (body,), tag.start, body.end))
            if not self.accept(","):
                break
        end = self.take(")")
        return self.node("match", children=(subject, *cases), start=token.start, end=end.end)


def parse_expression(text, *, path="expression", span=None, limits=ExpressionLimits()):
    if (
        type(text) is not str
        or type(path) is not str
        or span is not None
        and type(span) is not C0SourceSpan
        or type(limits) is not ExpressionLimits
    ):
        raise C0LawError("expression text or limits are malformed")
    source = ExpressionSource(text, path, span)
    parser = _Parser(source, limits)
    try:
        value = parser.expression()
        parser.take("<end>")
    except RecursionError:
        source.fail(
            "ExpressionBudget", parser.current.start, "bounded parser nesting", "depth limit"
        )
    return value
