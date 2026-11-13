/**
 * Vietnamese copy for the public tracking page.
 *
 * A real translation, not a transliteration of the English. Where a literal rendering
 * would read like machine output, the Vietnamese says the thing a Vietnamese speaker
 * would say -- "Theo dõi lô hàng" rather than a word-for-word calque of "Track your
 * shipment".
 *
 * Two constraints shaped the wording:
 *
 * Vietnamese runs roughly 20-30% longer than English for this kind of copy, so
 * `Design.md` section 15's 30% expansion allowance is not theoretical here. Sentences are
 * kept short and the layout is tested at 375 px with these strings, not with the English.
 *
 * Diacritics are preserved exactly. They are not decoration: *ma*, *má*, *mà*, *mả*, *mã*
 * and *mạ* are six different words, and a page that drops them is not merely ugly, it is
 * wrong.
 *
 * Every key must match `en.js`. `tests/publicI18n.test.js` fails if either catalogue
 * gains a key the other does not have.
 */

export const vi = {
  meta: {
    documentTitle: 'Theo dõi lô hàng — Solaris Express',
    languageName: 'Tiếng Việt',
    languageCode: 'vi',
    locale: 'vi-VN',
  },
  brand: {
    nameFirst: 'Solaris',
    nameSecond: 'Express',
    tagline: 'Theo dõi bưu kiện',
  },
  a11y: {
    skipToContent: 'Chuyển đến nội dung chính',
    languageSwitcher: 'Ngôn ngữ',
    mainContent: 'Nội dung chính',
    loading: 'Đang tải thông tin theo dõi',
    resultRegion: 'Kết quả theo dõi',
    timelineRegion: 'Các cập nhật của lô hàng',
    packagesRegion: 'Các kiện trong lô hàng này',
  },
  landing: {
    title: 'Theo dõi lô hàng của bạn',
    instruction:
      'Nhập mã lô hàng Solaris hoặc mã kiện in trên nhãn hoặc biên nhận của bạn.',
    fieldLabel: 'Mã lô hàng Solaris hoặc mã kiện',
    placeholder: 'SX-CAV-7K9D2M4R8T6W',
    exampleLabel: 'Ví dụ',
    exampleHint:
      'Mã lô hàng có dạng SX-CAV-7K9D2M4R8T6W. Mã kiện có thêm số thứ tự, ví dụ SX-CAV-7K9D2M4R8T6W-01. Chữ hoa, chữ thường và khoảng trắng đều được chấp nhận.',
    submit: 'Theo dõi',
    submitting: 'Đang kiểm tra…',
    emptyError: 'Vui lòng nhập mã lô hàng Solaris hoặc mã kiện.',
    helpLink: 'Liên hệ Solaris Express',
    privacyNote:
      'Chúng tôi chỉ hiển thị trạng thái của lô hàng bạn tra cứu. Nội dung bạn nhập không được lưu trong trình duyệt.',
  },
  result: {
    summaryTitle: 'Tóm tắt lô hàng',
    shipmentId: 'Mã lô hàng Solaris',
    copyId: 'Sao chép mã lô hàng',
    copied: 'Đã sao chép',
    route: 'Tuyến',
    status: 'Trạng thái',
    from: 'Từ',
    to: 'Đến',
    packages: 'Số kiện',
    scannedPackage: 'Kiện bạn đã quét',
    estimatedDelivery: 'Dự kiến giao hàng',
    estimatedBadge: 'Dự kiến',
    estimatedNote:
      'Đây là dự kiến được ghi nhận khi đặt lô hàng. Đây không phải là cam kết.',
    deliveredOn: 'Đã giao',
    cancelledOn: 'Đã huỷ',
    packagesTitle: 'Các kiện hàng',
    packageSelected: 'Kiện bạn đã quét',
    packageCancelled: 'Đã huỷ',
    packageDelivered: 'Đã giao',
    timelineTitle: 'Cập nhật',
    timelineEmpty: 'Chưa có cập nhật nào được công bố cho lô hàng này.',
    timelineEmptyBody:
      'Solaris công bố cập nhật khi lô hàng đạt một mốc mà chúng tôi xác nhận được. Vui lòng quay lại sau.',
    appliesTo: 'Áp dụng cho',
    trackAnother: 'Tra cứu lô hàng khác',
    unknownCity: 'Chưa xác định',
  },
  freshness: {
    label: 'Cách lô hàng này được theo dõi',
    manual_updates: 'Cập nhật do nhân viên Solaris nhập',
    manual_updates_detail:
      'Mỗi cập nhật bên dưới được nhân viên của chúng tôi ghi nhận khi đã xác nhận. Trang này không tự động làm mới.',
    external_link_only: 'Chỉ có liên kết của hãng vận chuyển',
    external_link_only_detail:
      'Solaris chưa công bố cập nhật riêng cho lô hàng này. Bên dưới là liên kết đến trang theo dõi của hãng vận chuyển. Chúng tôi không đọc trang đó thay bạn.',
    no_public_milestones: 'Chưa có cập nhật nào được công bố',
    no_public_milestones_detail:
      'Lô hàng đã được xác nhận. Solaris chưa công bố mốc nào cho lô hàng này. Trang này không tự động làm mới.',
    tracking_unavailable: 'Không có thông tin theo dõi',
    tracking_unavailable_detail:
      'Hiện chúng tôi không có thông tin theo dõi cho lô hàng này. Vui lòng liên hệ Solaris Express.',
    demo: 'Dữ liệu minh hoạ',
    demo_detail:
      'Đây là bản ghi thử nghiệm. Đây không phải lô hàng thật và mọi thông tin bên dưới đều là giả lập.',
    cancelled: 'Lô hàng đã huỷ',
    cancelled_detail:
      'Lô hàng này đã bị huỷ. Vui lòng liên hệ Solaris Express nếu bạn vẫn đang chờ gửi hàng.',
    lastUpdate: 'Cập nhật gần nhất',
    sourceManual: 'Cập nhật thủ công',
  },
  callout: {
    exceptionTitle: 'Lô hàng này cần được xử lý',
    exceptionBody:
      'Có sự cố làm gián đoạn lô hàng này. Vui lòng liên hệ Solaris Express kèm mã lô hàng Solaris để chúng tôi kiểm tra.',
    unavailableTitle: 'Chúng tôi không thể hiển thị thông tin theo dõi',
    unavailableBody:
      'Vui lòng liên hệ Solaris Express kèm mã lô hàng Solaris để được hỗ trợ.',
    contact: 'Liên hệ Solaris Express',
    carrierLink: '{{name}}: mở trang theo dõi',
    carrierLinkNote:
      'Liên kết này mở trang web của hãng vận chuyển trong tab mới. Solaris không đọc trang đó, nên thông tin hai bên có thể khác nhau.',
    // Tên chặng chung (chủ dự án, 22/10/2026): không bao giờ là tên đối tác. ĐỀ XUẤT, CHỜ DUYỆT.
    trackingNames: {
      master_tracking: 'Theo dõi chặng chính',
      last_mile_tracking: 'Theo dõi chặng cuối',
    },
  },
  errors: {
    notFoundTitle: 'Không tìm thấy lô hàng',
    notFoundBody:
      'Vui lòng kiểm tra lại mã lô hàng Solaris hoặc mã kiện trên nhãn hoặc biên nhận rồi thử lại. Mã có dạng SX-CAV-7K9D2M4R8T6W.',
    rateLimitedTitle: 'Bạn đã tra cứu quá nhiều lần',
    rateLimitedBody:
      'Bạn đã gửi rất nhiều yêu cầu tra cứu từ kết nối này. Vui lòng đợi khoảng {{seconds}} giây rồi thử lại.',
    rateLimitedBodyGeneric:
      'Bạn đã gửi rất nhiều yêu cầu tra cứu từ kết nối này. Vui lòng đợi một lát rồi thử lại.',
    networkTitle: 'Không kết nối được với Solaris Express',
    networkBody: 'Vui lòng kiểm tra kết nối mạng và thử lại.',
    tryAgain: 'Thử lại',
  },
  routes: {
    VCA: 'Việt Nam đến Canada',
    CAV: 'Canada đến Việt Nam',
    CAD: 'Nội địa Canada',
    XUS: 'Canada và Hoa Kỳ',
  },
  countries: {
    CA: 'Canada',
    VN: 'Việt Nam',
    US: 'Hoa Kỳ',
  },
  status: {
    booked: 'Đã đặt',
    awaiting_parcel: 'Đang chờ nhận hàng',
    received_at_solaris: 'Đã nhận hàng tại kho',
    processing: 'Đang xử lý',
    departed_origin: 'Đã rời nước gửi',
    in_transit: 'Đang vận chuyển',
    customs_processing: 'Đang làm thủ tục hải quan',
    arrived_destination: 'Đã đến nước nhận',
    out_for_delivery: 'Đang giao hàng',
    partially_delivered: 'Đã giao một phần',
    delivered: 'Đã giao',
    delivery_attempted: 'Đã thử giao hàng',
    exception: 'Bị chậm trễ',
    return_in_progress: 'Đang hoàn trả',
    returned: 'Đã hoàn trả',
    cancelled: 'Đã huỷ',
    tracking_unavailable: 'Không có thông tin theo dõi',
  },
  progress: {
    // Vietnamese has no plural inflection here, so both forms are the same sentence.
    // Both keys exist so the shared component does not need to know that.
    summaryOne: 'Đã giao {{delivered}} trên {{active}} kiện',
    summaryMany: 'Đã giao {{delivered}} trên {{active}} kiện',
    cancelledCountOne: '{{count}} kiện đã bị huỷ',
    cancelledCountMany: '{{count}} kiện đã bị huỷ',
  },
};

export default vi;
