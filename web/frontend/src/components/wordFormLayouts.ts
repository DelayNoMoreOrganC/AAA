export interface LayoutCell {
  text?: string
  field?: string
  derived?: string
  suffix?: string
  prefix?: string
  colspan?: number
  multiline?: boolean
  linesField?: string
  lineIndex?: number
  remainingLines?: boolean
  align?: 'left' | 'center' | 'right'
  className?: string
  organizationName?: boolean
  allowCustomInput?: boolean
}

export interface LayoutRow {
  height: number
  cells: LayoutCell[]
}

export interface LayoutTableBlock {
  type: 'table'
  columns: number[]
  rows: LayoutRow[]
  className?: string
}

export interface LayoutParagraphBlock {
  type: 'paragraph'
  className?: string
  runs: Array<{ text?: string; field?: string }>
}

export interface LayoutQuestionsBlock {
  type: 'questions'
  questions: string[]
}

export interface LayoutTextBlock {
  type: 'text'
  className?: string
  text: string
}

export type LayoutBlock = LayoutTableBlock | LayoutParagraphBlock | LayoutQuestionsBlock | LayoutTextBlock

export interface WordFormPage {
  title?: string
  subtitle?: string
  subtitleFromOrganization?: boolean
  titleClass?: string
  blocks: LayoutBlock[]
}

export interface WordFormLayout {
  pages: WordFormPage[]
}

const approvalTable: LayoutTableBlock = {
  type: 'table',
  columns: [18.9, 20.8, 11.3, 13.2, 35.8],
  rows: [
    { height: 8.2, cells: [
      { text: '案件类别', align: 'center' }, { field: '案件类别', align: 'center' },
      { text: '合同号', align: 'center' }, { field: '合同号', colspan: 2 },
    ] },
    { height: 8.2, cells: [
      { text: '委 托 人', align: 'center' }, { field: '委托人', colspan: 2 },
      { text: '当事人', align: 'center' }, { field: '当事人' },
    ] },
    { height: 8.2, cells: [
      { text: '委托人电话', align: 'center' }, { field: '委托人电话', colspan: 2 },
      { text: '传 真', align: 'center' }, { text: '' },
    ] },
    { height: 8.0, cells: [
      { text: '收费标准', align: 'center' }, { field: '收费标准' },
      { text: '地 址', align: 'center' }, { field: '地址', colspan: 2 },
    ] },
    { height: 8.5, cells: [
      { text: '对方当事人', align: 'center' }, { field: '对方当事人', colspan: 4 },
    ] },
    { height: 25, cells: [{ prefix: '案情简介：', field: '案情简介', colspan: 5, multiline: true, className: 'top-cell' }] },
    { height: 35, cells: [{ text: '承办律师意见：', colspan: 5, align: 'left', className: 'top-cell', allowCustomInput: true }] },
    { height: 35, cells: [{ text: '主任审批意见：', colspan: 5, align: 'left', className: 'top-cell', allowCustomInput: true }] },
    { height: 9, cells: [{ prefix: '立案日期：', field: '收案日期', colspan: 5 }] },
    { height: 12, cells: [{ text: '备  注：', colspan: 5, align: 'left', className: 'top-cell', allowCustomInput: true }] },
  ],
}

const archiveTable: LayoutTableBlock = {
  type: 'table',
  columns: [18.7, 20.8, 12.1, 16.1, 3.8, 28.5],
  rows: [
    { height: 8, cells: [
      { text: '案件类别', align: 'center' }, { field: '案件类别', align: 'center' },
      { text: '合同号', align: 'center' }, { field: '合同号', colspan: 3 },
    ] },
    { height: 8, cells: [{ text: '承办律师', align: 'center' }, { field: '承办律师', colspan: 5 }] },
    { height: 8, cells: [{ text: '委 托 人', align: 'center' }, { field: '委托人', colspan: 5 }] },
    { height: 8, cells: [{ text: '当 事 人', align: 'center' }, { field: '当事人', colspan: 5 }] },
    { height: 8, cells: [{ text: '对方当事人', align: 'center' }, { field: '对方当事人', colspan: 5 }] },
    { height: 15, cells: [{ text: '案   由', align: 'center' }, { field: '案由', colspan: 5, multiline: true }] },
    { height: 10.8, cells: [
      { text: '收案日期', align: 'center' }, { field: '收案日期', colspan: 2, align: 'center' },
      { text: '结案日期', align: 'center' }, { field: '结案日期', colspan: 2, align: 'center' },
    ] },
    { height: 14.6, cells: [
      { text: '审理法院', align: 'center' }, { field: '审理法院', colspan: 2, multiline: true },
      { text: '审 级', align: 'center' }, { field: '审级', colspan: 2, align: 'center' },
    ] },
    { height: 19, cells: [{ text: '法院收案号', align: 'center' }, { field: '法院收案号', colspan: 5, multiline: true }] },
    { height: 23, cells: [{ text: '审（办）结果', align: 'center' }, { field: '审（办）结果', colspan: 5, multiline: true }] },
    { height: 9, cells: [{ text: '归档日期', align: 'center' }, { field: '归档日期', colspan: 5, align: 'center' }] },
    { height: 10, cells: [
      { text: '立 卷 人', align: 'center' }, { field: '立卷人', colspan: 2, align: 'center' },
      { text: '卷内页数', colspan: 2, align: 'center' }, { derived: 'volume_page_count', suffix: ' 页', align: 'right' },
    ] },
    { height: 10, cells: [
      { text: '档 案 号', align: 'center' }, { text: '', colspan: 2 },
      { text: '保存年限', colspan: 2, align: 'center' }, { text: '' },
    ] },
    { height: 11, cells: [{ text: '备    注', align: 'center' }, { text: '', colspan: 5 }] },
  ],
}

const closeReportTable: LayoutTableBlock = {
  type: 'table',
  columns: [11.2, 7.3, 6.8, 29.3, 7.8, 10.3, 0.8, 26.8],
  rows: [
    { height: 12, cells: [{ text: '案  件  类  别', colspan: 3, align: 'center' }, { field: '案件类别', colspan: 5, align: 'center' }] },
    { height: 12, cells: [{ text: '委 托 人 名 称', colspan: 3, align: 'center' }, { field: '委托人', colspan: 5 }] },
    { height: 12, cells: [{ text: '案件或项目名称', colspan: 3, align: 'center' }, { field: '案件或项目名称', colspan: 5, multiline: true }] },
    { height: 43.4, cells: [{ text: '结\n案\n小\n结', align: 'center' }, { field: '结案小结', colspan: 7, multiline: true, className: 'top-cell' }] },
    { height: 44, cells: [{ text: '委\n托\n人\n对\n服\n务\n质\n量\n意\n见', align: 'center', className: 'vertical-label' }, { field: '委托人对服务质量意见', colspan: 7, multiline: true, className: 'top-cell' }] },
    { height: 12, cells: [
      { text: '应收业务费', colspan: 2, align: 'center' }, { field: '应收业务费', colspan: 2, align: 'center' },
      { text: '已收业务费', colspan: 3, align: 'center' }, { field: '已收业务费', align: 'center' },
    ] },
    { height: 12, cells: [
      { text: '尚欠业务费', colspan: 2, align: 'center' }, { field: '尚欠业务费', colspan: 2, align: 'center' },
      { text: '应退业务费', colspan: 3, align: 'center' }, { field: '应退业务费', align: 'center' },
    ] },
    { height: 20.7, cells: [{ text: '承办律师\n意    见', colspan: 2, align: 'center' }, { text: '', colspan: 6 }] },
    { height: 22, cells: [{ text: '主    任\n审批意见', colspan: 2, align: 'center' }, { text: '', colspan: 6 }] },
    { height: 12, cells: [
      { text: '结案日期', colspan: 2, align: 'center' }, { field: '结案日期', colspan: 3, align: 'center' },
      { text: '备注', align: 'center' }, { text: '', colspan: 2 },
    ] },
  ],
}

const qualityTable: LayoutTableBlock = {
  type: 'table',
  columns: [13.3, 6.7, 20, 4.4, 17.8, 37.8],
  rows: [
    { height: 8.1, cells: [{ text: '律师事务所', colspan: 2, align: 'center' }, { organizationName: true, colspan: 4, align: 'center' }] },
    { height: 8.2, cells: [
      { text: '案号', align: 'center' }, { field: '法院收案号', colspan: 3 },
      { text: '承办律师', align: 'center' }, { field: '承办律师' },
    ] },
    { height: 8, cells: [{ text: '委托人联系地址及电话', colspan: 3, align: 'center' }, { field: '委托人联系地址及电话', colspan: 3 }] },
  ],
}

const deliveryTable: LayoutTableBlock = {
  type: 'table',
  columns: [6.9, 28.3, 6.6, 16.6, 12.9, 12.9, 10.2],
  rows: [
    { height: 20, cells: [
      { text: '序号', align: 'center' }, { text: '材料名称', align: 'center' }, { text: '页数', align: 'center' },
      { text: '送达\n时间', align: 'center' }, { text: '送达人', align: 'center' }, { text: '接收人', align: 'center' }, { text: '备注', align: 'center' },
    ] },
    { height: 12.5, cells: [{ text: '1', align: 'center' }, { text: '委托代理合同', align: 'center' }, { text: '' }, { text: '' }, { text: '' }, { text: '' }, { text: '' }] },
    { height: 13, cells: [{ text: '2', align: 'center' }, { text: '委托人须知', align: 'center' }, { text: '1', align: 'center' }, { text: '' }, { text: '' }, { text: '' }, { text: '' }] },
    { height: 13, cells: [{ text: '3', align: 'center' }, { text: '律师所收款发票', align: 'center' }, { text: '1', align: 'center' }, { text: '' }, { text: '' }, { text: '' }, { text: '' }] },
    { height: 12.5, cells: [{ text: '4', align: 'center' }, { text: '质量监督卡', align: 'center' }, { text: '1', align: 'center' }, { text: '' }, { text: '' }, { text: '' }, { text: '' }] },
    ...Array.from({ length: 5 }, (_, index): LayoutRow => ({
      height: 13,
      cells: [
        { text: String(index + 5), align: 'center' },
        { linesField: '法院文件清单', lineIndex: index, remainingLines: index === 4, multiline: true },
        { text: '' }, { text: '' }, { text: '' }, { text: '' }, { text: '' },
      ],
    })),
    { height: 12.5, cells: [{ text: '' }, { text: '' }, { text: '' }, { text: '' }, { text: '' }, { text: '' }, { text: '' }] },
  ],
}

const qualityQuestions = [
  '是否由律师事务所与委托人签订委托代理合同',
  '是否由律师事务所向委托人收取律师费并如实出具发票',
  '接受委托后承办律师是否在律师费外收取了其他额外报酬或财物',
  '接受委托前承办律师是否向委托人作过虚假承诺',
  '接受委托后承办律师是否有无正当理由而不按时出庭参加诉讼、仲裁或有其他拒绝辩护、代理现象',
  '接受委托后承办律师是否有敷衍推诿、不尽职尽责的现象',
  '在委托代理合同中约定代收有关法律文书的，承办律师是否及时向委托人送达判决书、调解书、裁定书等法律文书',
  '承办律师与委托人是否办妥本案有关证据资料的交接手续',
]

const clientNotice = [
  '为了保障委托人、律师事务所及律师各方的合法权益，根据《中华人民共和国律师法》及《律师执业行为规范》等有关规定，律师接受委托的，应当告知委托人如下事项：',
  '一、委托人要求律师办理的事项应当合法，不得要求律师通过不正当手段与办案机关、政府部门及其工作人员进行沟通，不得要求承办律师对委托事项的办理结果作出承诺。',
  '二、委托人应当按照委托合同的约定，按时、足额支付律师费。以下情况律师事务所不予退费：（1）委托人同时委托他人的；（2）律师完成委托事项后，无正当理由委托人认为结果不理想，或者认为律师事务所收费过高的；（3）非因受托人原因，委托人终止委托合同的；（4）委托合同约定的其他情形。',
  '三、委托人的委托的诉讼或非诉讼事项均具有不同程度的法律风险，律师承办的业务受到办案机关、政府部门和相关当事方的制约，委托人的主张及律师的法律意见有部分或全部不被采纳的可能。',
  '四、委托人有权向承办律师了解委托事项的办理情况。',
  '五、律师执业必须遵守宪法和法律，恪守律师职业道德和执业纪律。律师执业必须以事实为根据，以法律为准绳。',
  '六、律师不得以诋毁其他律师事务所、律师，支付介绍费，向当事人明示或者暗示与办案机关、政府部门及其工作人员有特殊关系等不正当手段承揽业务，不得以不实宣传等方式承揽业务。',
  '七、律师承办业务，须由律师事务所与委托人签订书面委托合同，按有关规定收取律师费，并向委托人统一开具发票。律师不得私自接受委托，私自向委托人收取费用或财物。',
  '八、律师不得以非律师身份从事法律服务。',
  '九、委托人发现承办律师在履行委托合同过程中执业有违规行为的，可以向承办律师所在律师所、律师协会及司法行政部门投诉。',
  '委托人确认，委托人已知晓上述内容。',
]

export const wordFormLayouts: Record<string, WordFormLayout> = {
  '立案审批表': { pages: [{ title: '立 案 审 批 表', subtitleFromOrganization: true, blocks: [approvalTable] }] },
  '档案卷宗': { pages: [{ title: '律师业务档案卷宗', subtitleFromOrganization: true, titleClass: 'archive-title', blocks: [archiveTable] }] },
  '结案报告表': { pages: [{ title: '结 案 报 告 表', subtitleFromOrganization: true, blocks: [closeReportTable] }] },
  '送达材料清单': { pages: [{
    title: '律师所送达材料清单',
    blocks: [
      { type: 'paragraph', className: 'delivery-meta case-number', runs: [{ text: '案号：' }, { field: '法院收案号' }] },
      { type: 'paragraph', className: 'delivery-meta', runs: [{ text: '委托方：' }, { field: '委托人' }] },
      { type: 'paragraph', className: 'delivery-meta', runs: [{ text: '承办律师：' }, { field: '承办律师' }] },
      { type: 'text', className: 'delivery-note', text: '律师在接办案件中填写，若送达给当事人的内容多，律师可视情况在空白栏目添加。' },
      deliveryTable,
    ],
  }] },
  '质量监督卡': { pages: [
    {
      title: '律 师 办 案 质 量 监 督 卡',
      blocks: [
        qualityTable,
        { type: 'questions', questions: qualityQuestions },
        { type: 'text', className: 'quality-evaluation', text: '9、对承办律师办理本案总的评价　　好□　较好□　一般□　较差□　差□' },
        { type: 'text', className: 'quality-suggestion', text: '10、对律师办理本案的意见和建议（内容较多可另附页）' },
        { type: 'text', className: 'quality-signature', text: '委托人（签章）：　　　　　　　　　年　　月　　日' },
        { type: 'text', className: 'quality-note', text: '说明：此卡由律师事务所在办理委托手续时，与背面的《委托人须知》一起发给委托人，由委托人签收。案件办结后，请委托人填写此卡并及时交回律师事务所；如有不便，也可直接将此卡交该律师事务所的主管司法局或市律师协会。' },
      ],
    },
    {
      title: '委 托 人 须 知',
      subtitle: '历史参考待律所核定；现行适用内容请由律所确认',
      titleClass: 'notice-title',
      blocks: [
        ...clientNotice.map((text): LayoutTextBlock => ({ type: 'text', className: 'notice-paragraph', text })),
        { type: 'text', className: 'notice-signature', text: '委托人（签章）：　　　　　　　　　年　　月　　日' },
        { type: 'text', className: 'complaint-phones', text: '投诉渠道：请向所属律所核实主管司法局及律师协会的现行渠道。' },
      ],
    },
  ] },
}

