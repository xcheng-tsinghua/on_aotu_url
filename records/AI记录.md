目标：
你需要在浏览器中进行自动化操作，使用 Onshape Web 界面从 Onshape 公开模型列表中收集高质量的公开 CAD 模型，所有数据保存到 D:\document\DeepLearning\on_aotu_url\，候选最大数量：100。

重要约束：

1. 不要使用 Onshape REST API。
2. 不要使用 MiniMax 或任何 LLM API。
3. 不要使用任何付费 API。
4. 不要要求用户提供搜索关键词。
5. 使用如下账号密码登陆 Onshape：ukuykuy@rech.edu.kg，rws2D6r9wP#。
6. 登录后，工具应自动打开 Onshape 公开选项卡/页面，向下滚动公开模型列表以加载更多公开模型，打开候选模型，检查其 Part Studio 特征树，并使用确定性规则进行过滤。
7. 过滤逻辑必须是确定性的、基于规则的、可复现且可解释的。
8. 工具应收集满足规则的 Onshape 模型链接，包括 did, wid, eid，并以 JSON 和 CSV 导出结果。

高质量 Onshape 模型的定义：
只有当模型中所有活动且未压缩的建模特征都属于允许命令白名单时，该模型才被视为高质量。

允许的活动特征类型：

* Sketch
* Extrude
* Revolve
* Sweep
* Loft
* Chamfer
* Fillet
* Plane
* CPlane

拒绝规则：

1. 如果模型包含活动且未压缩的 Import 特征，则拒绝。
2. 如果模型包含活动且未压缩的 Derived 特征，则拒绝。
3. 如果模型包含任何不在白名单之外的活动且未压缩的特征，则拒绝。
4. 如果任何活动特征具有错误或再生失败状态，则拒绝。
5. 如果特征树无法可靠读取，则将模型标记为不确定，而不是通过。

压缩特征规则：
如果模型包含不在白名单中的不支持特征，但这些特征被压缩且不影响最终模型，则该模型仍可通过。输出中应记录这些已压缩的不支持特征，但不应导致拒绝。


主要工作流：

1. 打开 Onshape。
2. 如果用户尚未登录，自动登录。
3. 检测到登录后，自动导航到 Onshape 公开选项卡/页面。
4. 向下滚动公开模型列表，以渐进式加载更多公开模型。
5. 从加载的列表中收集候选公开模型卡片/链接。
6. 对候选 URL 进行去重。
7. 打开每个候选公开模型。
8. 查找文档中可用的 Part Studio。
9. 打开第一个有效的 Part Studio，或者如果配置了则检查多个 Part Studio。
10. 等待模型视口和左侧特征树完全加载。
11. 从页面提取特征树，特征树较长时，可能需要上下滚动以显示特征树中全部特征。
12. 将每个特征解析为结构化数据。
13. 使用确定性规则评估模型。
14. 保存截图和结构化结果。
15. 继续处理，直到检查完配置的候选最大数量。
16. 导出通过、拒绝、不确定和摘要报告。


候选来源：
候选来源应为 Onshape Web UI 中显示的公开模型列表。

特征数据模式：
每个提取的特征应包括：
{
"index": int,
"raw_text": string,
"feature_name": string,
"feature_type": string,
"is_suppressed": bool,
"has_error": bool,
"is_import": bool,
"is_derived": bool
}

候选结果模式：
{
"url": string,
"document_name": string | null,
"part_studio_name": string | null,
"status": "passed" | "rejected" | "uncertain",
"reason": string,
"active_feature_histogram": {
"Sketch": int,
"Extrude": int,
"Revolve": int,
"Sweep": int,
"Loft": int,
"Chamfer": int,
"Fillet": int,
"Plane": int,
"CPlane": int
},
"active_unsupported_features": [
{
"index": int,
"feature_name": string,
"feature_type": string,
"raw_text": string
}
],
"suppressed_unsupported_features": [
{
"index": int,
"feature_name": string,
"feature_type": string,
"raw_text": string
}
],
"has_active_import": bool,
"has_active_derived": bool,
"has_active_error": bool,
"screenshot_path": string | null
}
