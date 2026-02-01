/**
 * Validation Module - Unified Export
 *
 * 统一导出验证模块的所有公共 API，供测试和应用使用
 */

// Main validator functions
export {
  validateWorkflowClient,
  isWorkflowValid,
  getValidationSummary,
  groupErrorsByNode,
  getErrorsByType,
  getWarningsByType
} from './validator';

// Validation utilities
export { detectCircularDependency } from './circularDependency';
export { validateFieldReferences } from './fieldReference';
export { detectDanglingNodes } from './danglingNode';

// Type definitions
export type {
  WorkflowDefinition,
  NodeDefinition,
  EdgeDefinition,
  ValidationResult,
  ValidationError,
  ValidationWarning,
  CircularDependencyContext,
  MissingFieldReferenceContext,
  DanglingNodeContext
} from './types';

// Type guard functions
export {
  isMissingFieldReferenceError,
  isCircularDependencyError,
  isDanglingNodeWarning
} from './types';

// Test utilities
export { adaptFixtureWorkflow } from '../../tests/fixtures/fixtureAdapter';
