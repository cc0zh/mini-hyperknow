# 清除异步命令前，先证明它仍属于你

## 问题不在响应成功，而在谁有权清理

页面把未确认命令放入sessionStorage，是为了刷新后能以同一身份重试。异步请求的寿命却可能长于页面：

1. 页面A保存命令A并发请求，随后离开页面，请求尚未返回。
2. 后继页面在相同存储key下保存命令B。
3. 请求A终于成功，旧闭包无条件removeItem(key)，把B一并删掉。

A的成功是真的，清理却是错的。key只标识共享位置，不标识当前值的主人；“这是我写过的key”不是“现在存的仍是我的命令”。

## 把删除变成有条件的所有权释放

先读当前存储值，再比较命令身份；仍匹配才能删除。当前页面内存状态也单独做同样比较：它可能已经更新，不能因为存储匹配就顺便清空新状态。页面卸载后则不再执行页面清理或更新UI。

下面是思路示意，不是另一套实现：

```typescript
function owns(stored, completed) {
  return stored?.body.client_command_id === completed.body.client_command_id
    && stored.path === completed.path
    && stored.method === completed.method
}

if (!mounted) return
if (owns(readStored(key), completed)) removeStored(key)
if (owns(currentPending, completed)) clearPending()
```

方法与路径一起比较，避免只凭一个ID误认不同命令。完整请求体仍应原样保留供重试；若存储读取失败，就不能证明所有权，应保守保留，而不是“失败了先清空”。服务端命令幂等与前端所有权解决不同问题：前者防双写，后者防丢失尚待确认的命令。

这是单页前端对迟到闭包的逻辑保护，不是跨标签的原子CAS锁。不要据此宣称覆盖所有浏览器竞争；真正需要跨写入者协调时，仍要先明确共享存储范围和同步机制。

## 如何自检

- A完成时存储仍是A：允许释放；已被B替换：不得删除B。
- 页面卸载后A返回：不得更新后继页面状态或清理其待确认命令。
- 请求结果未知：保留原方法、路径、请求体及命令ID；不能偷偷新建命令重试。

直接验证所有权predicate可以覆盖身份判断，但不能替代所有跨页面时序的真实浏览器验收。本次精确迟到A／B时序尚未在浏览器复现，验证边界见[来源计划](../../exec-plans/completed/20261022-real-practice-exams.md#内置浏览器事实)；实现入口为use-quiz-command与quiz-state。
