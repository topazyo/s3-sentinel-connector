# docs/architecture.md

# S3 to Sentinel Connector Architecture

## Overview

The S3 to Sentinel Connector is a high-performance, secure system for transferring logs from AWS S3 to Microsoft Sentinel. The system incorporates ML-powered enhancements for intelligent log processing and anomaly detection.

## System Components

### 1. Core Components

```mermaid
graph TD
    A[AWS S3] --> B[S3 Handler]
    B --> C[Log Parser]
    C --> D[ML Processor]
    D --> E[Sentinel Router]
    E --> F[Microsoft Sentinel]
```

#### S3 Handler
- Manages AWS S3 connections
- Implements efficient batch processing
- Handles retry logic and error recovery
- Provides streaming capabilities

#### Log Parser
- Supports multiple log formats
- Implements format detection
- Performs field normalization
- Validates log integrity

#### ML Processor
- Performs anomaly detection
- Classifies log priority
- Identifies patterns
- Updates models in real-time

#### Sentinel Router
- Manages Sentinel connections
- Handles data transformation
- Implements batching logic
- Ensures delivery guarantees

### 2. Security Layer

```mermaid
graph LR
    A[Credential Manager] --> B[Encryption]
    B --> C[Access Control]
    C --> D[Audit Logging]
```

- Secure credential management
- Data encryption at rest and in transit
- Role-based access control
- Comprehensive audit logging

### 3. Monitoring System

```mermaid
graph TD
    A[Metrics Collection] --> B[Alert Manager]
    B --> C[Dashboard]
    A --> D[Log Analytics]
```

- Real-time metrics collection
- Configurable alerting
- Performance monitoring
- Health checks

## Data Flow

1. **Ingestion**
   ```plaintext
   S3 Event → S3 Handler → Raw Log Data
   ```

2. **Processing**
   ```plaintext
   Raw Log → Parser → Structured Data → ML Enhancement → Enriched Log
   ```

3. **Delivery**
   ```plaintext
   Enriched Log → Sentinel Router → Microsoft Sentinel
   ```

## Performance Considerations

- Batch processing optimization
- Caching strategies
- Connection pooling
- Resource management

## Security Measures

- Encryption in transit and at rest
- Secure credential handling
- Access control
- Audit logging