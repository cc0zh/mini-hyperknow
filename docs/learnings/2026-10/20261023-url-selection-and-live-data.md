# 用 URL 保留阅读位置，让实时数据只更新内容

列表与详情同屏时，用户正在看的条目和服务端推荐的下一项，是两种不同状态。推荐项会随学习进度改变；阅读位置应该随用户导航改变。把两者绑定，刷新数据就可能把用户带离正在看的内容。

## 从一次默认值开始

课程总览按下面的顺序寻找单元：

```ts
const unit = course?.units.find(item => item.unit_id === requestedUnit)
  ?? course?.units.find(item => item.unit_id === course.next_item?.unit_id)
  ?? course?.units[0]
```

第一次缺少有效选择时，用 `replace` 把得到的单元 ID 写入 URL。之后 URL 成为阅读位置的依据，`next_item` 只负责提示下一项学习活动。浏览器刷新、分享链接和前后退都能恢复选择，也不需要再维护一份本地 selectedUnit 状态。

## 两个容易踩的坑

用户明确选择单元时使用正常导航，才能留下可前后退的记录；补全默认值或修复失效 ID 时使用 replace，避免返回时再次经过无效地址。修改一个参数前先复制 `URLSearchParams`，保留其他参数。

不要在每次数据变化时把选择重设为 `next_item`。只要当前 ID 仍存在，就继续使用它；只有单元被删除或 URL 无效时才采用回退规则。单元 ID 比数组下标稳定，排序改变也不会指向另一个单元。

## 怎样验证

从真实保存的课程进入，选择其他单元，依次刷新、后退和前进；再访问带无效 ID 和额外查询参数的地址。应恢复正确单元，且额外参数保留。整个浏览过程只产生读取请求，课程版本不变。

对应实现：[CourseOverview.tsx](../../../web/src/pages/CourseOverview.tsx)；回归检查：[course-overview.spec.ts](../../../web/e2e/course-overview.spec.ts)。
