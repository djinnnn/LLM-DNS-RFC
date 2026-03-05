# DNS over TLS (DoT) Extension

## 概述

本扩展为DNS形式化验证项目添加了DNS over TLS (DoT)协议支持，基于原有的Maude形式化模型。

## 主要特性
- **TLS会话管理**: 完整的TLS连接状态跟踪
- **DoT协议支持**: 标准DoT端口(853)和消息格式
- **安全增强**: 所有DNS查询通过TLS加密传输
- **向后兼容**: 与现有DNS模型完全兼容
- **性能分析**: DoT vs 传统DNS的性能对比

### 基本DoT查询示例
```bash
cd Maude
maude dot-extension/test/example-dot-simple.maude
```

## 扩展说明

### 新增数据类型
- DoTSession: TLS会话管理
- DoTQuery/DoTResponse: DoT消息类型
- TLSState: TLS连接状态

### 新增Actor类型
- DoTNameserver: 支持DoT的名称服务器
- 扩展的Resolver: 支持DoT查询的解析器

### 端口配置
- DoT标准端口: 853
- 传统DNS端口: 53

## 设计原则
- 模块化: 每个功能独立模块
- 可扩展: 易于添加新的安全协议
- 标准化: 遵循RFC 7858 DoT标准