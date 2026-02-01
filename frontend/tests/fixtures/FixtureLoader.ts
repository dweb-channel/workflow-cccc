/**
 * Fixture Loader
 *
 * 加载和管理测试 fixture 数据
 */

import fixturesData from '../../../tests/fixtures/validation_test_cases.json';

export interface FixtureTestCase {
  id: string;
  since_version: string;
  phase: string;
  priority: string;
  tags: string[];
  description: string;
  workflow: any;
  expected_validation_result: any;
  test_instructions?: any;
}

export class FixtureLoader {
  /**
   * 获取指定 ID 的测试用例
   */
  static getTestCase(id: string): FixtureTestCase | undefined {
    return fixturesData.validation_test_cases.find(tc => tc.id === id);
  }

  /**
   * 获取所有测试用例
   */
  static getAllTestCases(): FixtureTestCase[] {
    return fixturesData.validation_test_cases;
  }

  /**
   * 按优先级获取测试用例
   */
  static getTestCasesByPriority(priority: string): FixtureTestCase[] {
    return fixturesData.validation_test_cases.filter(tc => tc.priority === priority);
  }

  /**
   * 获取所有 P0 测试用例
   */
  static getP0TestCases(): FixtureTestCase[] {
    return this.getTestCasesByPriority('P0');
  }

  /**
   * 获取fixture 元数据
   */
  static getMetadata() {
    return {
      version: fixturesData.version,
      lastUpdated: fixturesData.last_updated,
      schemaVersion: fixturesData.schema_version,
      description: fixturesData.description
    };
  }
}
