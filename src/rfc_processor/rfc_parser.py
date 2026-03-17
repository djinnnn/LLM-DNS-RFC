import re
import networkx as nx
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional, Set, Tuple

class RFCGraphBuilder:
    """
    V1: RFC 文档结构图构建器
    节点:
        - RFCDocument
        - Section
    边:
        - has_section
        - has_subsection
        - 
    """

    def __init__(self, rfc_id: str):
        self.rfc_id = self._normalize_rfc_id(rfc_id)
        self.graph = nx.DiGraph()

    # =========================
    # Public API
    # =========================
    def parse_xml_string(self, xml_content: str) -> nx.DiGraph:
        root = self._parse_xml_root(xml_content)

        # 先建文档节点
        doc_title = self._extract_xml_document_title(root)
        self._add_document_node(title=doc_title, source_format="xml")

        # 收集所有 section
        sections = self._extract_sections_from_xml(root)

        # 先建所有 section 节点
        for sec in sections:
            self._add_section_node(
                sec_num=sec["sec_num"],
                title=sec["title"],
                text=sec["text"],
                is_appendix=sec["is_appendix"],
                is_reference_section=self._is_reference_title(sec["title"]),
            )

        # 再统一建边
        self._build_document_section_edges()
        self._build_subsection_edges()
        self._build_cross_reference_edges()

        return self.graph

    def parse_text_string(self, raw_text: str, title: Optional[str] = None) -> nx.DiGraph:
        text = self._clean_text_rfc(raw_text)

        # 先建文档节点
        self._add_document_node(title=title or "", source_format="txt")

        # 抽取 section
        sections = self._extract_sections_from_text(text)

        # 建 section 节点
        for sec in sections:
            self._add_section_node(
                sec_num=sec["sec_num"],
                title=sec["title"],
                text=sec["text"],
                is_appendix=sec["is_appendix"],
                is_reference_section=self._is_reference_title(sec["title"]),
            )

        # 建边
        self._build_document_section_edges()
        self._build_subsection_edges()
        self._build_cross_reference_edges()

        return self.graph

    def get_graph(self) -> nx.DiGraph:
        return self.graph

    def get_document_id(self) -> str:
        return self.rfc_id

    def get_section_node(self, section_id: str) -> Optional[Dict[str, Any]]:
        if not self.graph.has_node(section_id):
            return None
        return dict(self.graph.nodes[section_id])

    # =========================
    # Node / Edge helpers
    # =========================
    def _add_document_node(self, title: str, source_format: str) -> None:
        self.graph.add_node(
            self.rfc_id,
            node_type="RFCDocument",
            rfc_id=self.rfc_id,
            title=title.strip(),
            source_format=source_format,
        )

    def _add_section_node(
        self,
        sec_num: str,
        title: str,
        text: str,
        is_appendix: bool,
        is_reference_section: bool,
    ) -> None:
        section_id = self._make_section_id(sec_num)

        self.graph.add_node(
            section_id,
            node_type="Section",
            section_id=section_id,
            rfc_id=self.rfc_id,
            sec_num=sec_num,
            title=title.strip(),
            text=text.strip(),
            is_appendix=is_appendix,
            is_reference_section=is_reference_section,
        )

    def _build_document_section_edges(self) -> None:
        for node_id, data in self.graph.nodes(data=True):
            if data.get("node_type") == "Section":
                sec_num = data.get("sec_num", "")
                # 只有当该节点没有父节点时，才将其挂载到文档根节点
                if self._get_parent_sec_num(sec_num) is None:
                    self.graph.add_edge(
                        self.rfc_id,
                        node_id,
                        edge_type="has_section",
                    )

    def _build_subsection_edges(self) -> None:
        # 统一二次扫描，避免父节点必须先出现的问题
        section_nodes: List[Tuple[str, Dict[str, Any]]] = [
            (nid, data)
            for nid, data in self.graph.nodes(data=True)
            if data.get("node_type") == "Section"
        ]

        existing = {nid for nid, _ in section_nodes}

        for node_id, data in section_nodes:
            sec_num = data["sec_num"]
            parent_sec_num = self._get_parent_sec_num(sec_num)
            if parent_sec_num is None:
                continue

            parent_id = self._make_section_id(parent_sec_num)
            if parent_id in existing:
                self.graph.add_edge(
                    parent_id,
                    node_id,
                    edge_type="has_subsection",
                )

    # =========================
    # XML parsing
    # =========================
    def _parse_xml_root(self, xml_content: str) -> ET.Element:
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            raise ValueError(f"Failed to parse RFC XML: {e}") from e
        return root

    def _strip_ns(self, tag: str) -> str:
        if not isinstance(tag, str):
            return str(tag)
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag

    def _find_first_child_by_localname(self, parent: ET.Element, name: str) -> Optional[ET.Element]:
        for child in parent:
            if self._strip_ns(child.tag) == name:
                return child
        return None

    def _extract_xml_document_title(self, root: ET.Element) -> str:
        # 常见路径: <rfc><front><title>...</title></front></rfc>
        for elem in root.iter():
            if self._strip_ns(elem.tag) == "front":
                title_elem = self._find_first_descendant_by_localname(elem, "title")
                if title_elem is not None:
                    return "".join(title_elem.itertext()).strip()
        return ""

    def _find_first_descendant_by_localname(self, parent: ET.Element, name: str) -> Optional[ET.Element]:
        for elem in parent.iter():
            if self._strip_ns(elem.tag) == name:
                return elem
        return None

    def _extract_sections_from_xml(self, root: ET.Element) -> List[Dict[str, Any]]:
        sections: List[Dict[str, Any]] = []

        for sec in root.iter():
            if self._strip_ns(sec.tag) != "section":
                continue

            sec_num = self._extract_xml_section_number(sec)
            if not sec_num:
                continue

            title = self._extract_xml_section_title(sec)
            text = self._extract_xml_section_text(sec)
            is_appendix = self._is_appendix_sec_num(sec_num)

            sections.append(
                {
                    "sec_num": sec_num,
                    "title": title,
                    "text": text,
                    "is_appendix": is_appendix,
                }
            )

        return sections

    def _extract_xml_section_number(self, sec: ET.Element) -> Optional[str]:
        """
        优先级:
        1) pn="section-4.1.2" / pn="section-a.1"
        2) anchor/name 中兜底可后续扩展
        """
        pn = sec.get("pn", "") or ""
        m = re.match(r"section-([A-Za-z0-9][A-Za-z0-9.\-]*)$", pn)
        if m:
            raw = m.group(1)
            return self._normalize_section_number(raw)

        # 某些 XML 可能没有 pn，V1 先不做更激进推断
        return None

    def _extract_xml_section_title(self, sec: ET.Element) -> str:
        name_elem = self._find_first_child_by_localname(sec, "name")
        if name_elem is None:
            return ""
        return "".join(name_elem.itertext()).strip()

    def _extract_xml_section_text(self, sec: ET.Element) -> str:
        """
        仅提取当前 section 的“直属内容”，排除嵌套 subsection。
        保留段落边界。
        """
        parts: List[str] = []

        for child in sec:
            tag = self._strip_ns(child.tag)

            if tag in {"section", "name"}:
                continue

            text = "".join(child.itertext()).strip()
            if text:
                parts.append(text)

        return "\n\n".join(parts).strip()

    # =========================
    # TXT parsing
    # =========================
    def _clean_text_rfc(self, raw_text: str) -> str:
        text = raw_text.replace("\r\n", "\n").replace("\r", "\n")

        # 核心清洗：利用换页符 \x0c 作为强特征，精准切除跨页的页脚和页眉
        # 匹配逻辑：空行 + [Page X] + 换页符 + 空行 + 新页眉(通常含RFC编号和日期) + 空行
        page_break_pattern = re.compile(
            r'\n*.*\[Page\s+\d+\].*\n\x0c\n.*?RFC.*?\n+', 
            re.IGNORECASE
        )
        text = page_break_pattern.sub('\n\n', text)

        # 压缩过多空行
        text = re.sub(r"\n{3,}", "\n\n", text)

        # 尝试移除目录区域
        text = self._remove_table_of_contents(text)

        return text.strip()

    def _remove_table_of_contents(self, text: str) -> str:
        """
        RFC 目录通常出现在前部，且包含大量 '1.  Title .... 3'
        这里采用保守策略：
        - 找 "Table of Contents" / "Contents"
        - 从其后开始，直到遇到正文第一节真正出现的位置
        """
        toc_match = re.search(r"(?im)^(table of contents|contents)\s*$", text)
        if not toc_match:
            return text

        toc_start = toc_match.start()

        # 正文第一节常见形态
        first_sec_match = re.search(r"(?m)^1(?:\.\d+)*\.?\s{2,}.+$", text[toc_match.end():])
        if not first_sec_match:
            return text

        # 找目录后第二次出现的第一节标题，作为正文开始
        first_abs = toc_match.end() + first_sec_match.start()
        second_match = re.search(
            r"(?m)^1(?:\.\d+)*\.?\s{2,}.+$",
            text[first_abs + 1:],
        )
        if second_match:
            body_start = first_abs + 1 + second_match.start()
            return text[:toc_start] + "\n\n" + text[body_start:]

        return text

    def _extract_sections_from_text(self, text: str) -> List[Dict[str, Any]]:
        """
        支持:
        - 1.  Introduction
        - 4.1.2  Foo
        - Appendix A.  Title
        - A.1.  Title
        """
        header_pattern = re.compile(
            r"""(?mx)
            ^
            (
                Appendix\ [A-Z](?:\.\d+)*      # Appendix A / Appendix A.1
                |
                [1-9]\d*(?:\.\d+)*            # 1 / 1.2 / 3.4.5
                |
                [A-Z](?:\.\d+)*               # A / A.1 / B.2.3
            )
            \.?
            \s{2,}
            (.+?)\s*$
            """
        )

        matches = list(header_pattern.finditer(text))
        sections: List[Dict[str, Any]] = []

        for i, match in enumerate(matches):
            raw_num = match.group(1).strip()
            title = match.group(2).strip()

            sec_num = self._normalize_text_section_number(raw_num)

            start_pos = match.end()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start_pos:end_pos].strip()

            sections.append(
                {
                    "sec_num": sec_num,
                    "title": title,
                    "text": content,
                    "is_appendix": self._is_appendix_sec_num(sec_num),
                }
            )

        return sections

    # =========================
    # Normalization helpers
    # =========================
    def _normalize_rfc_id(self, rfc_id: str) -> str:
        s = rfc_id.strip().upper()
        if not s.startswith("RFC"):
            s = f"RFC{s}"
        return s

    def _make_section_id(self, sec_num: str) -> str:
        return f"{self.rfc_id}_Sec{sec_num}"

    def _normalize_section_number(self, raw: str) -> str:
        s = raw.strip()

        # XML pn 里 appendix 可能是 a / a.1，统一大写
        if re.fullmatch(r"[A-Za-z](?:\.\d+)*", s):
            return s.upper()

        return s

    def _normalize_text_section_number(self, raw_num: str) -> str:
        s = raw_num.strip()

        # Appendix A / Appendix A.1 -> A / A.1
        m = re.match(r"Appendix\s+([A-Z](?:\.\d+)*)$", s, flags=re.IGNORECASE)
        if m:
            return m.group(1).upper()

        # A / A.1
        if re.fullmatch(r"[A-Z](?:\.\d+)*", s):
            return s.upper()

        return s

    def _is_appendix_sec_num(self, sec_num: str) -> bool:
        return bool(re.fullmatch(r"[A-Z](?:\.\d+)*", sec_num))

    def _get_parent_sec_num(self, sec_num: str) -> Optional[str]:
        # 4.1.2 -> 4.1
        # A.2.1 -> A.2
        # 4 / A -> None
        if "." not in sec_num:
            return None
        return sec_num.rsplit(".", 1)[0]

    def _is_reference_title(self, title: str) -> bool:
        t = title.strip().lower()
        return t in {
            "references",
            "normative references",
            "informative references",
        }

    def _extract_precise_references(self, text: str) -> set[Tuple[str, Optional[str]]]:
        """
        基于正则管道，提取细粒度的 (RFC编号, 章节号) 双元组。
        使用就地擦除技术防止不同模式的正则发生重叠匹配。
        """
        refs = set()
        
        # 模式 1: 前置章节号的外部引用 (如 "Section 2 of RFC 5741", "Section 4.2.2 of [RFC1035]")
        pattern1 = re.compile(r'Section\s+([A-Za-z0-9.]+)\s+of\s+\[?RFC\s*(\d+)\]?', re.IGNORECASE)
        for match in pattern1.finditer(text):
            sec_num = match.group(1).rstrip('.')
            rfc_id = f"RFC{match.group(2)}"
            refs.add((rfc_id, sec_num))
            
        # 擦除模式 1
        text = pattern1.sub(' ', text)
        
        # 模式 2: 后置章节号的外部引用 (如 "([RFC7766], Section 8)", "[RFC1035] (Section 4.2)")
        pattern2 = re.compile(r'\[?RFC\s*(\d+)\]?[\s,\(]*Section\s+([A-Za-z0-9.]+)', re.IGNORECASE)
        for match in pattern2.finditer(text):
            rfc_id = f"RFC{match.group(1)}"
            sec_num = match.group(2).rstrip('.')
            refs.add((rfc_id, sec_num))
            
        # 擦除模式 2
        text = pattern2.sub(' ', text)
        
        # 模式 3: 内部章节引用 (如 "in Section 4.e", "(Section 4.2)")
        pattern3 = re.compile(r'Section\s+([A-Za-z0-9.]+)', re.IGNORECASE)
        for match in pattern3.finditer(text):
            sec_num = match.group(1).rstrip('.')
            refs.add((self.rfc_id, sec_num))
            
        # 擦除模式 3
        text = pattern3.sub(' ', text)
        
        precise_rfc_ids = {r[0] for r in refs if r[0] != self.rfc_id}
        
        # 模式 4: 兜底的粗粒度文档级引用 (如 "[RFC1035]")
        fallback_pattern = re.compile(r'\[RFC\s*(\d+)\]', re.IGNORECASE)
        for match in fallback_pattern.finditer(text):
            rfc_id = f"RFC{match.group(1)}"
            if rfc_id not in precise_rfc_ids:
                refs.add((rfc_id, None))
                
        return refs

    def _build_cross_reference_edges(self) -> None:
        """
        扫描文档，建立跨文档引用边 (cites_normative 等) 与文档内引用边 (cites_internal)
        """
        normative_set, informative_set = self._parse_references_sections()

        for node_id, data in list(self.graph.nodes(data=True)):
            if data.get("node_type") != "Section":
                continue
            
            if data.get("is_reference_section"):
                continue

            text = data.get("text", "")
            precise_refs = self._extract_precise_references(text)
            
            for target_doc_id, sec_num in precise_refs:
                # 判定引用性质，新增内部引用类型
                if target_doc_id == self.rfc_id:
                    edge_type = "cites_internal"
                elif target_doc_id in normative_set:
                    edge_type = "cites_normative"
                elif target_doc_id in informative_set:
                    edge_type = "cites_informative"
                else:
                    edge_type = "cites_unspecified"

                # 拼接高精度的目标节点 ID
                if sec_num:
                    target_id = f"{target_doc_id}_Sec{sec_num}"
                else:
                    target_id = target_doc_id

                self.graph.add_edge(node_id, target_id, edge_type=edge_type)

    def _parse_references_sections(self) -> tuple[Set[str], Set[str]]:
        """
        提取规范性引用 (Normative) 和资料性引用 (Informative) 的 RFC 集合。
        """
        normative_rfcs = set()
        informative_rfcs = set()

        for _, data in self.graph.nodes(data=True):
            if not data.get("is_reference_section"):
                continue
            
            title = data.get("title", "").lower()
            text = data.get("text", "")
            
            # 提取该段落中出现的所有 RFC 编号
            cited_rfcs = {f"RFC{num}" for num in re.findall(r'RFC\s*(\d+)', text, re.IGNORECASE)}
            
            if "normative" in title:
                normative_rfcs.update(cited_rfcs)
            elif "informative" in title:
                informative_rfcs.update(cited_rfcs)
            else:
                # 如果标题只是 "References" 没有细分，保守视为 normative
                normative_rfcs.update(cited_rfcs)

        return normative_rfcs, informative_rfcs

