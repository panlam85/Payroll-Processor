from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from employee_workspace import EmployeeWorkspaceMixin


class Tree:
    def __init__(self, selected):
        self.selected = list(selected)
        self.focused = None
        self.region = 'cell'

    def selection(self):
        return tuple(self.selected)

    def identify_region(self, x, y):
        return self.region

    def identify_row(self, y):
        return '0060'

    def selection_toggle(self, item):
        self.selected.remove(item) if item in self.selected else self.selected.append(item)

    def focus(self, item=None):
        if item is not None:
            self.focused = item
        return self.focused

    def focus_set(self):
        pass

    def item(self, item, option):
        return (item, 'Employee ' + item)


def workspace(selected):
    gui = EmployeeWorkspaceMixin()
    gui.employees_tree = Tree(selected)
    gui.employee_merge_button = Mock()
    gui.employee_employment_button = Mock()
    return gui


@pytest.mark.parametrize('count', [0, 1, 2, 3])
def test_merge_requires_exactly_two_selected_employees(count):
    gui = workspace(['60', '0060', '61'][:count])
    gui._update_employee_actions()
    gui.employee_merge_button.state.assert_called_once_with(['!disabled'] if count == 2 else ['disabled'])
    gui.employee_employment_button.state.assert_called_once_with(['!disabled'] if count == 1 else ['disabled'])


def test_command_click_toggles_one_row_without_dropping_the_other():
    gui = workspace(['60'])
    event = SimpleNamespace(x=20, y=40)
    assert gui._toggle_employee_selection(event) == 'break'
    assert gui.employees_tree.selection() == ('60', '0060')
    gui.employee_merge_button.state.assert_called_with(['!disabled'])
    gui._toggle_employee_selection(event)
    assert gui.employees_tree.selection() == ('60',)
    gui.employee_merge_button.state.assert_called_with(['disabled'])
    gui.employees_tree.region = 'heading'
    assert gui._toggle_employee_selection(event) is None
    assert gui.employees_tree.selection() == ('60',)


def test_merge_uses_only_selected_pair_and_respects_edit_lock():
    gui = workspace(['0060', '60'])
    gui.db_config = {'enabled': True}
    gui._employee_change_allowed = Mock(return_value=True)
    gui._show_employee_merge = Mock()
    gui._open_employee_merge()
    gui._show_employee_merge.assert_called_once_with(
        [('0060', 'Employee 0060'), ('60', 'Employee 60')], gui.db_config)
    gui._show_employee_merge.reset_mock()
    gui._employee_change_allowed.return_value = False
    gui._open_employee_merge()
    gui._show_employee_merge.assert_not_called()
    gui._employee_change_allowed.return_value = True
    gui.employees_tree.selected = ['60']
    gui._open_employee_merge()
    gui._show_employee_merge.assert_not_called()
